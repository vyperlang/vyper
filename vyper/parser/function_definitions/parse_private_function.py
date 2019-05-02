import ast
from typing import (
    Any,
    List,
)

from vyper.exceptions import (
    FunctionDeclarationException,
)
from vyper.parser.context import (
    Context,
)
from vyper.parser.expr import (
    Expr,
)
from vyper.parser.function_definitions.utils import (
    get_default_names_to_set,
    get_nonreentrant_lock,
    get_sig_statements,
    make_unpacker,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    getpos,
    make_setter,
)
from vyper.parser.stmt import (
    parse_body,
)
from vyper.signatures import (
    FunctionSignature,
    sig_utils,
)
from vyper.signatures.function_signature import (
    VariableRecord,
)
from vyper.types.types import (
    BaseType,
    ByteArrayLike,
    get_size_of_type,
)
from vyper.utils import (
    MemoryPositions,
)


def get_private_arg_copier(total_size: int, memory_dest: int) -> List[Any]:
    """
    Copy arguments.
    For private functions, MSTORE arguments and callback pointer from the stack.

    :param  total_size: total size to copy
    :param  memory_dest: base memory position to copy to
    :return: LLL list that copies total_size of memory
    """

    copier: List[Any] = ['seq']
    for pos in range(0, total_size, 32):
        copier.append(['mstore', memory_dest + pos, 'pass'])
    return copier


def validate_private_function(code: ast.FunctionDef, sig: FunctionSignature) -> None:
    """ Validate private function defintion """
    if sig.is_default_func():
        raise FunctionDeclarationException(
            'Default function may only be public.', code
        )


def parse_private_function(code: ast.FunctionDef,
                           sig: FunctionSignature,
                           context: Context) -> LLLnode:
    """
    Parse a private function (FuncDef), and produce full function body.

    :param sig: the FuntionSignature
    :param code: ast of function
    :return: full sig compare & function body
    """

    validate_private_function(code, sig)

    # Get nonreentrant lock
    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(sig, context.global_ctx)

    # Create callback_ptr, this stores a destination in the bytecode for a private
    # function to jump to after a function has executed.
    clampers = []

    # Allocate variable space.
    context.memory_allocator.increase_memory(sig.max_copy_size)

    _post_callback_ptr = "{}_{}_post_callback_ptr".format(sig.name, sig.method_id)
    context.callback_ptr = context.new_placeholder(typ=BaseType('uint256'))
    clampers.append(
        LLLnode.from_list(
            ['mstore', context.callback_ptr, 'pass'],
            annotation='pop callback pointer',
        )
    )
    if sig.total_default_args > 0:
        clampers.append(['label', _post_callback_ptr])

    # private functions without return types need to jump back to
    # the calling function, as there is no return statement to handle the
    # jump.
    if sig.output_type is None:
        stop_func = [['jump', ['mload', context.callback_ptr]]]
    else:
        stop_func = [['stop']]

    # Generate copiers
    if len(sig.base_args) == 0:
        copier = ['pass']
        clampers.append(copier)
    elif sig.total_default_args == 0:
        copier = get_private_arg_copier(
            total_size=sig.base_copy_size,
            memory_dest=MemoryPositions.RESERVED_MEMORY
        )
        clampers.append(copier)

    # Fill variable positions
    for arg in sig.args:
        if isinstance(arg.typ, ByteArrayLike):
            mem_pos, _ = context.memory_allocator.increase_memory(32 * get_size_of_type(arg.typ))
            context.vars[arg.name] = VariableRecord(arg.name, mem_pos, arg.typ, False)
        else:
            context.vars[arg.name] = VariableRecord(
                arg.name,
                MemoryPositions.RESERVED_MEMORY + arg.pos,
                arg.typ,
                False,
            )

    # Private function copiers. No clamping for private functions.
    dyn_variable_names = [a.name for a in sig.base_args if isinstance(a.typ, ByteArrayLike)]
    if dyn_variable_names:
        i_placeholder = context.new_placeholder(typ=BaseType('uint256'))
        unpackers: List[Any] = []
        for idx, var_name in enumerate(dyn_variable_names):
            var = context.vars[var_name]
            ident = "_load_args_%d_dynarg%d" % (sig.method_id, idx)
            o = make_unpacker(ident=ident, i_placeholder=i_placeholder, begin_pos=var.pos)
            unpackers.append(o)

        if not unpackers:
            unpackers = ['pass']

        # 0 added to complete full overarching 'seq' statement, see private_label.
        unpackers.append(0)
        clampers.append(LLLnode.from_list(
            ['seq_unchecked'] + unpackers,
            typ=None,
            annotation='dynamic unpacker',
            pos=getpos(code),
        ))

    # Function has default arguments.
    if sig.total_default_args > 0:  # Function with default parameters.

        default_sigs = sig_utils.generate_default_arg_sigs(code, context.sigs, context.global_ctx)
        sig_chain: List[Any] = ['seq']

        for default_sig in default_sigs:
            sig_compare, private_label = get_sig_statements(default_sig, getpos(code))

            # Populate unset default variables
            set_defaults = []
            for arg_name in get_default_names_to_set(sig, default_sig):
                value = Expr(sig.default_values[arg_name], context).lll_node
                var = context.vars[arg_name]
                left = LLLnode.from_list(var.pos, typ=var.typ, location='memory',
                                         pos=getpos(code), mutable=var.mutable)
                set_defaults.append(make_setter(left, value, 'memory', pos=getpos(code)))
            current_sig_arg_names = [x.name for x in default_sig.args]

            # Load all variables in default section, if private,
            # because the stack is a linear pipe.
            copier_arg_count = len(default_sig.args)
            copier_arg_names = current_sig_arg_names

            # Order copier_arg_names, this is very important.
            copier_arg_names = [
                x.name
                for x in default_sig.args
                if x.name in copier_arg_names
            ]

            # Variables to be populated from calldata/stack.
            default_copiers: List[Any] = []
            if copier_arg_count > 0:
                # Get map of variables in calldata, with thier offsets
                offset = 4
                calldata_offset_map = {}
                for arg in default_sig.args:
                    calldata_offset_map[arg.name] = offset
                    offset += (
                        32
                        if isinstance(arg.typ, ByteArrayLike)
                        else get_size_of_type(arg.typ) * 32
                    )

                # Copy set default parameters from calldata
                dynamics = []
                for arg_name in copier_arg_names:
                    var = context.vars[arg_name]
                    if isinstance(var.typ, ByteArrayLike):
                        _size = 32
                        dynamics.append(var.pos)
                    else:
                        _size = var.size * 32
                    default_copiers.append(get_private_arg_copier(
                        memory_dest=var.pos,
                        total_size=_size,
                    ))

                # Unpack byte array if necessary.
                if dynamics:
                    i_placeholder = context.new_placeholder(typ=BaseType('uint256'))
                    for idx, var_pos in enumerate(dynamics):
                        ident = 'unpack_default_sig_dyn_%d_arg%d' % (default_sig.method_id, idx)
                        default_copiers.append(make_unpacker(
                            ident=ident,
                            i_placeholder=i_placeholder,
                            begin_pos=var_pos,
                        ))
                default_copiers.append(0)  # for over arching seq, POP

            sig_chain.append([
                'if', sig_compare,
                ['seq',
                    private_label,
                    LLLnode.from_list([
                        'mstore',
                        context.callback_ptr,
                        'pass',
                    ], annotation='pop callback pointer', pos=getpos(code)),
                    ['seq'] + set_defaults if set_defaults else ['pass'],
                    ['seq_unchecked'] + default_copiers if default_copiers else ['pass'],
                    ['goto', _post_callback_ptr]]
            ])

        # With private functions all variable loading occurs in the default
        # function sub routine.
        _clampers = [['label', _post_callback_ptr]]

        # Function with default parameters.
        o = LLLnode.from_list(
            [
                'seq',
                sig_chain,
                [
                    'if', 0,  # can only be jumped into
                    [
                        'seq',
                        ['seq'] + nonreentrant_pre + _clampers + [
                            parse_body(c, context)
                            for c in code.body
                        ] + nonreentrant_post + stop_func
                    ],
                ],
            ], typ=None, pos=getpos(code))

    else:
        # Function without default parameters.
        sig_compare, private_label = get_sig_statements(sig, getpos(code))
        o = LLLnode.from_list(
            [
                'if',
                sig_compare,
                ['seq'] + [private_label] + nonreentrant_pre + clampers + [
                    parse_body(c, context)
                    for c
                    in code.body
                ] + nonreentrant_post + stop_func
            ], typ=None, pos=getpos(code)
        )
        return o

    return o

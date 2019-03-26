from vyper.exceptions import (
    FunctionDeclarationException,
)
from vyper.parser.arg_clamps import (
    make_arg_clamper,
)
from vyper.parser.context import (
    Constancy,
    Context,
)
from vyper.parser.expr import (
    Expr,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.memory_allocator import (
    MemoryAllocator,
)
from vyper.parser.parser_utils import (
    getpos,
    make_setter,
)
from vyper.parser.stmt import (
    parse_body,
)
from vyper.signatures import (
    sig_utils,
)
from vyper.signatures.function_signature import (
    FunctionSignature,
    VariableRecord,
)
from vyper.types.types import (
    BaseType,
    ByteArrayLike,
    get_size_of_type,
)
from vyper.utils import (
    MemoryPositions,
    calc_mem_gas,
)


# Is a function the initializer?
def is_initializer(code):
    return code.name == '__init__'


# Is a function the default function?
def is_default_func(code):
    return code.name == '__default__'


def get_sig_statements(sig, pos):
    method_id_node = LLLnode.from_list(sig.method_id, pos=pos, annotation='%s' % sig.sig)

    if sig.private:
        sig_compare = 0
        private_label = LLLnode.from_list(
            ['label', 'priv_{}'.format(sig.method_id)],
            pos=pos, annotation='%s' % sig.sig
        )
    else:
        sig_compare = ['eq', ['mload', 0], method_id_node]
        private_label = ['pass']

    return sig_compare, private_label


def get_arg_copier(sig, total_size, memory_dest, offset=4):
    # Copy arguments.
    # For private function, MSTORE arguments and callback pointer from the stack.
    if sig.private:
        copier = ['seq']
        for pos in range(0, total_size, 32):
            copier.append(['mstore', memory_dest + pos, 'pass'])
    else:
        copier = ['calldatacopy', memory_dest, offset, total_size]

    return copier


def make_unpacker(ident, i_placeholder, begin_pos):
    start_label = 'dyn_unpack_start_' + ident
    end_label = 'dyn_unpack_end_' + ident
    return [
        'seq_unchecked',
        ['mstore', begin_pos, 'pass'],  # get len
        ['mstore', i_placeholder, 0],
        ['label', start_label],
        [  # break
            'if',
            ['ge', ['mload', i_placeholder], ['ceil32', ['mload', begin_pos]]],
            ['goto', end_label],
        ],
        [  # pop into correct memory slot.
            'mstore',
            ['add', ['add', begin_pos, 32], ['mload', i_placeholder]],
            'pass',
        ],
        ['mstore', i_placeholder, ['add', 32, ['mload', i_placeholder]]],  # increment i
        ['goto', start_label],
        ['label', end_label]]


def parse_private_function():
    pass


def parse_public_function():
    pass


def parse_function(code, sigs, origcode, global_ctx, _vars=None):
    """
    Parses a function and produces LLL code for the function, includes:
        - Signature method if statement
        - Argument handling
        - Clamping and copying of arguments
        - Function body
    """

    if _vars is None:
        _vars = {}
    sig = FunctionSignature.from_definition(
        code,
        sigs=sigs,
        custom_units=global_ctx._custom_units,
        custom_structs=global_ctx._structs,
        constants=global_ctx._constants
    )
    # Get base args for function.
    total_default_args = len(code.args.defaults)
    base_args = sig.args[:-total_default_args] if total_default_args > 0 else sig.args
    default_args = code.args.args[-total_default_args:]
    default_values = dict(zip([arg.arg for arg in default_args], code.args.defaults))
    # __init__ function may not have defaults.
    if sig.name == '__init__' and total_default_args > 0:
        raise FunctionDeclarationException("__init__ function may not have default parameters.")
    # Check for duplicate variables with globals
    for arg in sig.args:
        if arg.name in global_ctx._globals:
            raise FunctionDeclarationException(
                "Variable name duplicated between function arguments and globals: " + arg.name
            )

    nonreentrant_pre = [['pass']]
    nonreentrant_post = [['pass']]
    if sig.nonreentrant_key:
        nkey = global_ctx.get_nonrentrant_counter(sig.nonreentrant_key)
        nonreentrant_pre = [
            ['seq',
                ['assert', ['iszero', ['sload', nkey]]],
                ['sstore', nkey, 1]]]
        nonreentrant_post = [['sstore', nkey, 0]]

    # Create a local (per function) context.
    memory_allocator = MemoryAllocator()
    context = Context(
        vars=_vars,
        global_ctx=global_ctx,
        sigs=sigs,
        memory_allocator=memory_allocator,
        return_type=sig.output_type,
        constancy=Constancy.Constant if sig.const else Constancy.Mutable,
        is_payable=sig.payable,
        origcode=origcode,
        is_private=sig.private,
        method_id=sig.method_id
    )

    # Copy calldata to memory for fixed-size arguments
    max_copy_size = sum([
        32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
        for arg in sig.args
    ])
    base_copy_size = sum([
        32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
        for arg in base_args
    ])
    # context.next_mem += max_copy_size
    context.memory_allocator.increase_memory(max_copy_size)

    clampers = []

    # Create callback_ptr, this stores a destination in the bytecode for a private
    # function to jump to after a function has executed.
    _post_callback_ptr = "{}_{}_post_callback_ptr".format(sig.name, sig.method_id)
    if sig.private:
        context.callback_ptr = context.new_placeholder(typ=BaseType('uint256'))
        clampers.append(
            LLLnode.from_list(
                ['mstore', context.callback_ptr, 'pass'],
                annotation='pop callback pointer',
            )
        )
        if total_default_args > 0:
            clampers.append(['label', _post_callback_ptr])

    # private functions without return types need to jump back to
    # the calling function, as there is no return statement to handle the
    # jump.
    stop_func = [['stop']]
    if sig.output_type is None and sig.private:
        stop_func = [['jump', ['mload', context.callback_ptr]]]

    if not len(base_args):
        copier = 'pass'
    elif sig.name == '__init__':
        copier = ['codecopy', MemoryPositions.RESERVED_MEMORY, '~codelen', base_copy_size]
    else:
        copier = get_arg_copier(
            sig=sig,
            total_size=base_copy_size,
            memory_dest=MemoryPositions.RESERVED_MEMORY
        )
    clampers.append(copier)

    # Add asserts for payable and internal
    # private never gets payable check.
    if not sig.payable and not sig.private:
        clampers.append(['assert', ['iszero', 'callvalue']])

    # Fill variable positions
    for i, arg in enumerate(sig.args):
        if i < len(base_args) and not sig.private:

            clampers.append(make_arg_clamper(
                arg.pos,
                context.memory_allocator.get_next_memory_position(),
                arg.typ,
                sig.name == '__init__',
            ))
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
    dyn_variable_names = [a.name for a in base_args if isinstance(a.typ, ByteArrayLike)]
    if sig.private and dyn_variable_names:
        i_placeholder = context.new_placeholder(typ=BaseType('uint256'))
        unpackers = []
        for idx, var_name in enumerate(dyn_variable_names):
            var = context.vars[var_name]
            ident = "_load_args_%d_dynarg%d" % (sig.method_id, idx)
            o = make_unpacker(ident=ident, i_placeholder=i_placeholder, begin_pos=var.pos)
            unpackers.append(o)

        if not unpackers:
            unpackers = ['pass']

        clampers.append(LLLnode.from_list(
            # [0] to complete full overarching 'seq' statement, see private_label.
            ['seq_unchecked'] + unpackers + [0],
            typ=None,
            annotation='dynamic unpacker',
            pos=getpos(code),
        ))

    # Create "clampers" (input well-formedness checkers)
    # Return function body
    if sig.name == '__init__':
        o = LLLnode.from_list(
            ['seq'] + clampers + [parse_body(code.body, context)],
            pos=getpos(code),
        )
    elif is_default_func(sig):
        if len(sig.args) > 0:
            raise FunctionDeclarationException(
                'Default function may not receive any arguments.', code
            )
        if sig.private:
            raise FunctionDeclarationException(
                'Default function may only be public.', code,
            )
        o = LLLnode.from_list(
            ['seq'] + clampers + [parse_body(code.body, context)],
            pos=getpos(code),
        )
    else:

        if total_default_args > 0:  # Function with default parameters.
            function_routine = "{}_{}".format(sig.name, sig.method_id)
            default_sigs = sig_utils.generate_default_arg_sigs(code, sigs, global_ctx)
            sig_chain = ['seq']

            for default_sig in default_sigs:
                sig_compare, private_label = get_sig_statements(default_sig, getpos(code))

                # Populate unset default variables
                populate_arg_count = len(sig.args) - len(default_sig.args)
                set_defaults = []
                if populate_arg_count > 0:
                    current_sig_arg_names = {x.name for x in default_sig.args}
                    missing_arg_names = [
                        arg.arg
                        for arg
                        in default_args
                        if arg.arg not in current_sig_arg_names
                    ]
                    for arg_name in missing_arg_names:
                        value = Expr(default_values[arg_name], context).lll_node
                        var = context.vars[arg_name]
                        left = LLLnode.from_list(var.pos, typ=var.typ, location='memory',
                                                 pos=getpos(code), mutable=var.mutable)
                        set_defaults.append(make_setter(left, value, 'memory', pos=getpos(code)))

                current_sig_arg_names = {x.name for x in default_sig.args}
                base_arg_names = {arg.name for arg in base_args}
                if sig.private:
                    # Load all variables in default section, if private,
                    # because the stack is a linear pipe.
                    copier_arg_count = len(default_sig.args)
                    copier_arg_names = current_sig_arg_names
                else:
                    copier_arg_count = len(default_sig.args) - len(base_args)
                    copier_arg_names = current_sig_arg_names - base_arg_names
                # Order copier_arg_names, this is very important.
                copier_arg_names = [x.name for x in default_sig.args if x.name in copier_arg_names]

                # Variables to be populated from calldata/stack.
                default_copiers = []
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
                        calldata_offset = calldata_offset_map[arg_name]
                        if sig.private:
                            _offset = calldata_offset
                            if isinstance(var.typ, ByteArrayLike):
                                _size = 32
                                dynamics.append(var.pos)
                            else:
                                _size = var.size * 32
                            default_copiers.append(get_arg_copier(
                                sig=sig,
                                memory_dest=var.pos,
                                total_size=_size,
                                offset=_offset,
                            ))
                        else:
                            # Add clampers.
                            default_copiers.append(make_arg_clamper(
                                calldata_offset - 4,
                                var.pos,
                                var.typ,
                            ))
                            # Add copying code.
                            if isinstance(var.typ, ByteArrayLike):
                                _offset = ['add', 4, ['calldataload', calldata_offset]]
                            else:
                                _offset = calldata_offset
                            default_copiers.append(get_arg_copier(
                                sig=sig,
                                memory_dest=var.pos,
                                total_size=var.size * 32,
                                offset=_offset,
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
                        ['pass'] if not sig.private else LLLnode.from_list([
                            'mstore',
                            context.callback_ptr,
                            'pass',
                        ], annotation='pop callback pointer', pos=getpos(code)),
                        ['seq'] + set_defaults if set_defaults else ['pass'],
                        ['seq_unchecked'] + default_copiers if default_copiers else ['pass'],
                        ['goto', _post_callback_ptr if sig.private else function_routine]]
                ])

            # With private functions all variable loading occurs in the default
            # function sub routine.
            if sig.private:
                _clampers = [['label', _post_callback_ptr]]
            else:
                _clampers = clampers

            # Function with default parameters.
            o = LLLnode.from_list(
                [
                    'seq',
                    sig_chain,
                    [
                        'if', 0,  # can only be jumped into
                        [
                            'seq',
                            ['label', function_routine] if not sig.private else ['pass'],
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
                ], typ=None, pos=getpos(code))

    # Check for at leasts one return statement if necessary.
    if context.return_type and context.function_return_count == 0:
        raise FunctionDeclarationException(
            "Missing return statement in function '%s' " % sig.name, code
        )

    o.context = context
    o.total_gas = o.gas + calc_mem_gas(
        o.context.memory_allocator.get_next_memory_position()
    )
    o.func_name = sig.name
    return o

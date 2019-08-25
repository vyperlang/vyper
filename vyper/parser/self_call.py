import itertools

from vyper.exceptions import (
    ConstancyViolationException,
    StructureException,
    TypeMismatchException,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    getpos,
    pack_arguments,
)
from vyper.signatures.function_signature import (
    FunctionSignature,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    TupleLike,
    get_size_of_type,
    get_static_size_of_type,
    has_dynamic_data,
)


def call_lookup_specs(stmt_expr, context):
    from vyper.parser.expr import Expr

    method_name = stmt_expr.func.attr

    if len(stmt_expr.keywords):
        raise TypeMismatchException(
            "Cannot use keyword arguments in calls to functions via 'self'",
            stmt_expr,
        )
    expr_args = [
        Expr(arg, context).lll_node
        for arg in stmt_expr.args
    ]

    sig = FunctionSignature.lookup_sig(
        context.sigs,
        method_name,
        expr_args,
        stmt_expr,
        context,
    )

    return method_name, expr_args, sig


def make_call(stmt_expr, context):
    method_name, _, sig = call_lookup_specs(stmt_expr, context)

    if context.is_constant() and not sig.const:
        raise ConstancyViolationException(
            "May not call non-constant function '%s' within %s." % (
                method_name,
                context.pp_constancy(),
            ),
            getpos(stmt_expr)
        )

    if not sig.private:
        raise StructureException("Cannot call public functions via 'self'", stmt_expr)

    return call_self_private(stmt_expr, context, sig)


def call_make_placeholder(stmt_expr, context, sig):
    if sig.output_type is None:
        return 0, 0, 0

    output_placeholder = context.new_placeholder(typ=sig.output_type)
    out_size = get_size_of_type(sig.output_type) * 32
    returner = output_placeholder

    if not sig.private and isinstance(sig.output_type, ByteArrayLike):
        returner = output_placeholder + 32

    return output_placeholder, returner, out_size


def call_self_private(stmt_expr, context, sig):
    # ** Private Call **
    # Steps:
    # (x) push current local variables
    # (x) push arguments
    # (x) push jumpdest (callback ptr)
    # (x) jump to label
    # (x) pop return values
    # (x) pop local variables

    method_name, expr_args, sig = call_lookup_specs(stmt_expr, context)
    pre_init = []
    pop_local_vars = []
    push_local_vars = []
    pop_return_values = []
    push_args = []

    # Push local variables.
    var_slots = [
        (v.pos, v.size) for name, v in context.vars.items()
        if v.location == 'memory'
    ]
    if var_slots:
        var_slots.sort(key=lambda x: x[0])
        mem_from, mem_to = var_slots[0][0], var_slots[-1][0] + var_slots[-1][1] * 32

        i_placeholder = context.new_placeholder(BaseType('uint256'))
        local_save_ident = "_%d_%d" % (stmt_expr.lineno, stmt_expr.col_offset)
        push_loop_label = 'save_locals_start' + local_save_ident
        pop_loop_label = 'restore_locals_start' + local_save_ident

        if mem_to - mem_from > 320:
            push_local_vars = [
                    ['mstore', i_placeholder, mem_from],
                    ['label', push_loop_label],
                    ['mload', ['mload', i_placeholder]],
                    ['mstore', i_placeholder, ['add', ['mload', i_placeholder], 32]],
                    ['if', ['lt', ['mload', i_placeholder], mem_to],
                        ['goto', push_loop_label]]
            ]
            pop_local_vars = [
                ['mstore', i_placeholder, mem_to - 32],
                ['label', pop_loop_label],
                ['mstore', ['mload', i_placeholder], 'pass'],
                ['mstore', i_placeholder, ['sub', ['mload', i_placeholder], 32]],
                ['if', ['ge', ['mload', i_placeholder], mem_from],
                       ['goto', pop_loop_label]]
            ]
        else:
            push_local_vars = [['mload', pos] for pos in range(mem_from, mem_to, 32)]
            pop_local_vars = [['mstore', pos, 'pass'] for pos in range(mem_to-32, mem_from-32, -32)]

    # Push Arguments
    if expr_args:
        inargs, inargsize, arg_pos = pack_arguments(
            sig,
            expr_args,
            context,
            stmt_expr,
            return_placeholder=False,
        )
        push_args += [inargs]  # copy arguments first, to not mess up the push/pop sequencing.

        static_arg_size = 32 * sum(
                [get_static_size_of_type(arg.typ)
                    for arg in expr_args])
        static_pos = int(arg_pos + static_arg_size)
        needs_dyn_section = any(
                [has_dynamic_data(arg.typ)
                    for arg in expr_args])

        if needs_dyn_section:
            ident = 'push_args_%d_%d_%d' % (sig.method_id, stmt_expr.lineno, stmt_expr.col_offset)
            start_label = ident + '_start'
            end_label = ident + '_end'
            i_placeholder = context.new_placeholder(BaseType('uint256'))

            # Calculate copy start position.
            # Given | static | dynamic | section in memory,
            # copy backwards so the values are in order on the stack.
            # We calculate i, the end of the whole encoded part
            # (i.e. the starting index for copy)
            # by taking ceil32(len<arg>) + offset<arg> + arg_pos
            # for the last dynamic argument and arg_pos is the start
            # the whole argument section.
            idx = 0
            for arg in expr_args:
                if isinstance(arg.typ, ByteArrayLike):
                    last_idx = idx
                idx += get_static_size_of_type(arg.typ)
            push_args += [
                ['with', 'offset', ['mload', arg_pos + last_idx * 32],
                    ['with', 'len_pos', ['add', arg_pos, 'offset'],
                        ['with', 'len_value', ['mload', 'len_pos'],
                            ['mstore', i_placeholder,
                                ['add', 'len_pos', ['ceil32', 'len_value']]]]]]
            ]
            # loop from end of dynamic section to start of dynamic section,
            # pushing each element onto the stack.
            push_args += [

                ['label', start_label],
                ['if', ['lt', ['mload', i_placeholder], static_pos],
                    ['goto', end_label]],
                ['mload', ['mload', i_placeholder]],
                ['mstore', i_placeholder, ['sub', ['mload', i_placeholder], 32]],  # decrease i
                ['goto', start_label],
                ['label', end_label]
            ]

        # push static section
        push_args += [
            ['mload', pos] for pos in reversed(range(arg_pos, static_pos, 32))
        ]
    elif sig.args:
        raise StructureException(
            f"Wrong number of args for: {sig.name} (0 args given, expected {len(sig.args)})",
            stmt_expr
        )

    # Jump to function label.
    jump_to_func = [
        ['add', ['pc'], 6],  # set callback pointer.
        ['goto', 'priv_{}'.format(sig.method_id)],
        ['jumpdest'],
    ]

    # Pop return values.
    returner = [0]
    if sig.output_type:
        output_placeholder, returner, output_size = call_make_placeholder(stmt_expr, context, sig)
        if output_size > 0:
            dynamic_offsets = []
            if isinstance(sig.output_type, (BaseType, ListType)):
                pop_return_values = [
                    ['mstore', ['add', output_placeholder, pos], 'pass']
                    for pos in range(0, output_size, 32)
                ]
            elif isinstance(sig.output_type, ByteArrayLike):
                dynamic_offsets = [(0, sig.output_type)]
                pop_return_values = [
                    ['pop', 'pass'],
                ]
            elif isinstance(sig.output_type, TupleLike):
                static_offset = 0
                pop_return_values = []
                for out_type in sig.output_type.members:
                    if isinstance(out_type, ByteArrayLike):
                        pop_return_values.append(
                            ['mstore', ['add', output_placeholder, static_offset], 'pass']
                        )
                        dynamic_offsets.append(
                            (['mload', ['add', output_placeholder, static_offset]], out_type)
                        )
                    else:
                        pop_return_values.append(
                            ['mstore', ['add', output_placeholder, static_offset], 'pass']
                        )
                    static_offset += 32

            # append dynamic unpacker.
            dyn_idx = 0
            for in_memory_offset, _out_type in dynamic_offsets:
                ident = "%d_%d_arg_%d" % (stmt_expr.lineno, stmt_expr.col_offset, dyn_idx)
                dyn_idx += 1
                start_label = 'dyn_unpack_start_' + ident
                end_label = 'dyn_unpack_end_' + ident
                i_placeholder = context.new_placeholder(typ=BaseType('uint256'))
                begin_pos = ['add', output_placeholder, in_memory_offset]
                # loop until length.
                o = LLLnode.from_list(
                    ['seq_unchecked',
                        ['mstore', begin_pos, 'pass'],  # get len
                        ['mstore', i_placeholder, 0],
                        ['label', start_label],
                        [  # break
                            'if',
                            ['ge', ['mload', i_placeholder], ['ceil32', ['mload', begin_pos]]],
                            ['goto', end_label]
                        ],
                        [  # pop into correct memory slot.
                            'mstore',
                            ['add', ['add', begin_pos, 32], ['mload', i_placeholder]],
                            'pass',
                        ],
                        # increment i
                        ['mstore', i_placeholder, ['add', 32, ['mload', i_placeholder]]],
                        ['goto', start_label],
                        ['label', end_label]],
                    typ=None, annotation='dynamic unpacker', pos=getpos(stmt_expr))
                pop_return_values.append(o)

    call_body = list(itertools.chain(
        ['seq_unchecked'],
        pre_init,
        push_local_vars,
        push_args,
        jump_to_func,
        pop_return_values,
        pop_local_vars,
        [returner],
    ))
    # If we have no return, we need to pop off
    pop_returner_call_body = ['pop', call_body] if sig.output_type is None else call_body

    o = LLLnode.from_list(
        pop_returner_call_body,
        typ=sig.output_type,
        location='memory',
        pos=getpos(stmt_expr),
        annotation='Internal Call: %s' % method_name,
        add_gas_estimate=sig.gas
    )
    o.gas += sig.gas
    return o

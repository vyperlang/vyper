from vyper.exceptions import (
    ConstancyViolationException
)
from vyper.parser.lll_node import (
    LLLnode
)
from vyper.parser.parser_utils import (
    pack_arguments,
    getpos
)
from vyper.signatures.function_signature import (
    FunctionSignature
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    ListType,
    TupleType,
    ceil32,
    get_size_of_type,
)


def call_lookup_specs(stmt_expr, context):
    from vyper.parser.expr import Expr
    method_name = stmt_expr.func.attr
    expr_args = [Expr(arg, context).lll_node for arg in stmt_expr.args]
    sig = FunctionSignature.lookup_sig(context.sigs, method_name, expr_args, stmt_expr, context)
    return method_name, expr_args, sig


def make_call(stmt_expr, context):
    method_name, _, sig = call_lookup_specs(stmt_expr, context)

    if context.is_constant and not sig.const:
        raise ConstancyViolationException(
            "May not call non-constant function '%s' within a constant function." % (method_name),
            getpos(stmt_expr)
        )

    if sig.private:
        return call_self_private(stmt_expr, context, sig)
    else:
        return call_self_public(stmt_expr, context, sig)


def call_make_placeholder(stmt_expr, context, sig):
    if sig.output_type is None:
        return 0, 0, 0

    output_placeholder = context.new_placeholder(typ=sig.output_type)
    out_size = get_size_of_type(sig.output_type) * 32
    returner = output_placeholder

    if not sig.private and isinstance(sig.output_type, ByteArrayType):
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
    if context.vars:
        var_slots = [(v.pos, v.size) for name, v in context.vars.items()]
        var_slots.sort(key=lambda x: x[0])
        mem_from, mem_to = var_slots[0][0], var_slots[-1][0] + var_slots[-1][1] * 32
        push_local_vars = [
            ['mload', pos] for pos in range(mem_from, mem_to, 32)
        ]
        pop_local_vars = [
            ['mstore', pos, 'pass'] for pos in reversed(range(mem_from, mem_to, 32))
        ]

    # Push Arguments
    if expr_args:
        inargs, inargsize, arg_pos = pack_arguments(sig, expr_args, context, return_placeholder=False, pos=getpos(stmt_expr))
        push_args += [inargs]  # copy arguments first, to not mess up the push/pop sequencing.
        static_arg_count = len(expr_args) * 32
        static_pos = arg_pos + static_arg_count
        total_arg_size = ceil32(inargsize - 4)

        if len(expr_args) * 32 != total_arg_size:  # requires dynamic section.
            ident = 'push_args_%d_%d_%d' % (sig.method_id, stmt_expr.lineno, stmt_expr.col_offset)
            start_label = ident + '_start'
            end_label = ident + '_end'
            i_placeholder = context.new_placeholder(BaseType('uint256'))
            push_args += [
                ['mstore', i_placeholder, arg_pos + total_arg_size],
                ['label', start_label],
                ['if', ['lt', ['mload', i_placeholder], static_pos], ['goto', end_label]],
                ['if_unchecked', ['ne', ['mload', ['mload', i_placeholder]], 0], ['mload', ['mload', i_placeholder]]],
                ['mstore', i_placeholder, ['sub', ['mload', i_placeholder], 32]],  # decrease i
                ['goto', start_label],
                ['label', end_label]
            ]

        # push static section
        push_args += [
            ['mload', pos] for pos in reversed(range(arg_pos, static_pos, 32))
        ]

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
                    ['mstore', ['add', output_placeholder, pos], 'pass'] for pos in range(0, output_size, 32)
                ]
            elif isinstance(sig.output_type, ByteArrayType):
                dynamic_offsets = [(0, sig.output_type)]
                pop_return_values = [
                    ['pop', 'pass'],
                ]
            elif isinstance(sig.output_type, TupleType):
                static_offset = 0
                pop_return_values = []
                for out_type in sig.output_type.members:
                    if isinstance(out_type, ByteArrayType):
                        pop_return_values.append(['mstore', ['add', output_placeholder, static_offset], 'pass'])
                        dynamic_offsets.append((['mload', ['add', output_placeholder, static_offset]], out_type))
                    else:
                        pop_return_values.append(['mstore', ['add', output_placeholder, static_offset], 'pass'])
                    static_offset += 32

            # append dynamic unpacker.
            dyn_idx = 0
            for in_memory_offset, out_type in dynamic_offsets:
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
                        ['if', ['ge', ['mload', i_placeholder], ['ceil32', ['mload', begin_pos]]], ['goto', end_label]],  # break
                        ['mstore', ['add', ['add', begin_pos, 32], ['mload', i_placeholder]], 'pass'],  # pop into correct memory slot.
                        ['mstore', i_placeholder, ['add', 32, ['mload', i_placeholder]]],  # increment i
                        ['goto', start_label],
                        ['label', end_label]],
                    typ=None, annotation='dynamic unpacker', pos=getpos(stmt_expr))
                pop_return_values.append(o)

    o = LLLnode.from_list(
        ['seq_unchecked'] + pre_init +
        push_local_vars + push_args +
        jump_to_func +
        pop_return_values + pop_local_vars + [returner],
        typ=sig.output_type, location='memory', pos=getpos(stmt_expr), annotation='Internal Call: %s' % method_name,
        add_gas_estimate=sig.gas
    )
    o.gas += sig.gas
    return o


def call_self_public(stmt_expr, context, sig):
    # self.* style call to a public function.
    method_name, expr_args, sig = call_lookup_specs(stmt_expr, context)
    add_gas = sig.gas  # gas of call
    inargs, inargsize, _ = pack_arguments(sig, expr_args, context, pos=getpos(stmt_expr))
    output_placeholder, returner, output_size = call_make_placeholder(stmt_expr, context, sig)
    assert_call = [
        'assert', ['call', ['gas'], ['address'], 0, inargs, inargsize, output_placeholder, output_size]
    ]
    if output_size > 0:
        assert_call = ['seq', assert_call, returner]
    o = LLLnode.from_list(
        assert_call,
        typ=sig.output_type, location='memory',
        pos=getpos(stmt_expr), add_gas_estimate=add_gas, annotation='Internal Call: %s' % method_name)
    o.gas += sig.gas
    return o

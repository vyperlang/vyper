from .abi import (
    abi_encode,
    abi_type_of,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    getpos,
)
from vyper.types import (
    BaseType,
)

# Generate return code for stmt
def make_return_stmt(stmt, context, begin_pos, _size, loop_memory_position=None):
    from vyper.parser.function_definitions.utils import (
        get_nonreentrant_lock
    )
    _, nonreentrant_post = get_nonreentrant_lock(context.sig, context.global_ctx)
    if context.is_private:
        if loop_memory_position is None:
            loop_memory_position = context.new_placeholder(typ=BaseType('uint256'))

        # Make label for stack push loop.
        label_id = '_'.join([str(x) for x in (context.method_id, stmt.lineno, stmt.col_offset)])
        exit_label = f'make_return_loop_exit_{label_id}'
        start_label = f'make_return_loop_start_{label_id}'

        # Push prepared data onto the stack,
        # in reverse order so it can be popped of in order.
        if isinstance(begin_pos, int) and isinstance(_size, int):
            # static values, unroll the mloads instead.
            mloads = [
                ['mload', pos] for pos in range(begin_pos, _size, 32)
            ]
            return ['seq_unchecked'] + mloads + nonreentrant_post + \
                [['jump', ['mload', context.callback_ptr]]]
        else:
            mloads = [
                'seq_unchecked',
                ['mstore', loop_memory_position, _size],
                ['label', start_label],
                [  # maybe exit loop / break.
                    'if',
                    ['le', ['mload', loop_memory_position], 0],
                    ['goto', exit_label]
                ],
                [  # push onto stack
                    'mload',
                    ['add', begin_pos, ['sub', ['mload', loop_memory_position], 32]]
                ],
                [  # decrement i by 32.
                    'mstore',
                    loop_memory_position,
                    ['sub', ['mload', loop_memory_position], 32],
                ],
                ['goto', start_label],
                ['label', exit_label]
            ]
            return ['seq_unchecked'] + [mloads] + nonreentrant_post + \
                [['jump', ['mload', context.callback_ptr]]]
    else:
        return ['seq_unchecked'] + nonreentrant_post + [['return', begin_pos, _size]]


# Generate code for returning a tuple or struct.
def gen_tuple_return(stmt, context, sub):
    # Is from a call expression.
    if sub.args and len(sub.args[0].args) > 0 and sub.args[0].args[0].value == 'call':
        # self-call to public.
        mem_pos = sub
        mem_size = get_size_of_type(sub.typ) * 32
        return LLLnode.from_list(['return', mem_pos, mem_size], typ=sub.typ)

    elif (sub.annotation and 'Internal Call' in sub.annotation):
        mem_pos = sub.args[-1].value if sub.value == 'seq_unchecked' else sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        # Add zero padder if bytes are present in output.
        zero_padder = ['pass']
        byte_arrays = [
            (i, x)
            for i, x
            in enumerate(sub.typ.tuple_members())
            if isinstance(x, ByteArrayLike)
        ]
        if byte_arrays:
            i, x = byte_arrays[-1]
            zero_padder = zero_pad(bytez_placeholder=[
                'add',
                mem_pos,
                ['mload', mem_pos + i * 32]
            ])
        return LLLnode.from_list(['seq'] + [sub] + [zero_padder] + [
            make_return_stmt(stmt, context, mem_pos, mem_size)
        ], typ=sub.typ, pos=getpos(stmt), valency=0)

    abi_typ = abi_type_of(context.return_type)
    abi_bytes_needed = abi_typ.static_size() + abi_typ.dynamic_size_bound()
    dst, _ = context.memory_allocator.increase_memory(32 * abi_bytes_needed)
    return_buffer = LLLnode(dst, location='memory', annotation='return_buffer')

    encode_out = abi_encode(return_buffer, sub, pos=getpos(stmt), returns=True)
    return LLLnode.from_list(
            ['with', 'return_len', encode_out,
                make_return_stmt(stmt, context, return_buffer, 'return_len')
    ], typ=None, pos=getpos(stmt), valency=0)

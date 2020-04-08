from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    getpos,
    make_setter,
    zero_pad,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ensure_vyper_tuple,
    get_size_of_type,
)
from vyper.types.check import (
    check_assign,
)
from vyper.utils import (
    MemoryPositions,
)

from .abi import (
    abi_encode,
    abi_type_of,
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
            mloads = [ ['mload', pos]
                    for pos in range(begin_pos, begin_pos + _size, 32) ]
            mloads = list(reversed(mloads))
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
# actually this is generic code that should work for all types, just
# need to replace branches in stmt.py with this.
def gen_tuple_return(stmt, context, sub):
    typecheck_dummy = LLLnode(0, location='memory', typ=context.return_type)
    check_assign(typecheck_dummy, sub, pos=getpos(stmt))

    ctx_name = context.sig.name

    # for certain arguments (to return), we can skip some copies and
    # return the return buffer directly
    if sub.args and len(sub.args[0].args) > 0 and sub.args[0].args[0].value == 'call':
        print(f'DBG SELF CALL PUB')
        # self-call to public.
        mem_pos = sub
        # TODO more accurate: abi size bound.
        mem_size = get_size_of_type(sub.typ) * 32
        return LLLnode.from_list(['return', mem_pos, mem_size],
                typ=sub.typ,
                annotation=f'`{ctx_name}` return')

    # if the argument is a call to a private function and the data is
    # static (in the ABI sense), we can return the buffer directly
    is_private_call = sub.annotation and 'Internal Call' in sub.annotation
    if is_private_call and not abi_type_of(sub.typ).is_dynamic():
        print(f'DBG CALL PRIV STATIC')
        mem_pos = sub.args[-1].value \
                if sub.value == 'seq_unchecked' \
                else sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        return LLLnode.from_list(['seq'] + [sub] + [
            make_return_stmt(stmt, context, mem_pos, mem_size)
        ], typ=sub.typ, pos=getpos(stmt), valency=0)

    # if we are in a private call, just return the data unencoded
    if context.is_private:
        print(f'DBG IS PRIVATE')
        mem_pos = context.new_placeholder(context.return_type)
        mem_size = get_size_of_type(context.return_type) * 32
        dst = LLLnode(mem_pos, location='memory', typ=context.return_type)
        os = ['seq',
              make_setter(dst, sub, 'memory', pos=getpos(stmt)),
              make_return_stmt(stmt, context, mem_pos, mem_size)]
        return LLLnode.from_list(os,
                pos=getpos(stmt),
                annotation=f'fill `{ctx_name}` return buffer (unpacked)',
                typ=None,
                valency=0)

    ret_ty = context.return_type
    abi_typ = abi_type_of(ret_ty)
    abi_bytes_needed = abi_typ.static_size() + abi_typ.dynamic_size_bound()
    dst, _ = context.memory_allocator.increase_memory(abi_bytes_needed)
    return_buffer = LLLnode(dst,
            location='memory',
            annotation=f'`{ctx_name}` return buffer',
            typ=ret_ty)

    encode_out = abi_encode(return_buffer, sub, pos=getpos(stmt),
            returns=True,
            ensure_tuple=True)
    load_return_len = ['mload', MemoryPositions.FREE_VAR_SPACE]
    os = ['seq',
          ['mstore', MemoryPositions.FREE_VAR_SPACE, encode_out],
          make_return_stmt(stmt, context, return_buffer, load_return_len)]
    return LLLnode.from_list(os, typ=None, pos=getpos(stmt), valency=0,
            annotation=f'`{ctx_name}` abi-encode and return')

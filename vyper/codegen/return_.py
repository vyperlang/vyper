from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import getpos, zero_pad
from vyper.types import BaseType, ByteArrayLike, get_size_of_type
from vyper.types.check import check_assign
from vyper.utils import MemoryPositions

from .abi import abi_encode, abi_type_of, ensure_tuple


# Generate return code for stmt
def make_return_stmt(stmt, context, begin_pos, _size, loop_memory_position=None):
    from vyper.parser.function_definitions.utils import get_nonreentrant_lock

    _, nonreentrant_post = get_nonreentrant_lock(context.sig, context.global_ctx)
    if context.is_internal:
        if loop_memory_position is None:
            loop_memory_position = context.new_placeholder(typ=BaseType("uint256"))

        # Make label for stack push loop.
        label_id = "_".join([str(x) for x in (context.method_id, stmt.lineno, stmt.col_offset)])
        exit_label = f"make_return_loop_exit_{label_id}"
        start_label = f"make_return_loop_start_{label_id}"

        # Push prepared data onto the stack,
        # in reverse order so it can be popped of in order.
        if isinstance(begin_pos, int) and isinstance(_size, int):
            # static values, unroll the mloads instead.
            mloads = [["mload", pos] for pos in range(begin_pos, _size, 32)]
        else:
            mloads = [
                "seq_unchecked",
                ["mstore", loop_memory_position, _size],
                ["label", start_label],
                [  # maybe exit loop / break.
                    "if",
                    ["le", ["mload", loop_memory_position], 0],
                    ["goto", exit_label],
                ],
                [  # push onto stack
                    "mload",
                    ["add", begin_pos, ["sub", ["mload", loop_memory_position], 32]],
                ],
                [  # decrement i by 32.
                    "mstore",
                    loop_memory_position,
                    ["sub", ["mload", loop_memory_position], 32],
                ],
                ["goto", start_label],
                ["label", exit_label],
            ]

        # if we are in a for loop, we have to exit prior to returning
        exit_repeater = ["exit_repeater"] if context.forvars else []

        return (
            ["seq_unchecked"]
            + exit_repeater
            + mloads
            + nonreentrant_post
            + [["jump", ["mload", context.callback_ptr]]]
        )
    else:
        return ["seq_unchecked"] + nonreentrant_post + [["return", begin_pos, _size]]


# Generate code for returning a tuple or struct.
def gen_tuple_return(stmt, context, sub):
    # Is from a call expression.
    if sub.args and len(sub.args[0].args) > 0 and sub.args[0].args[0].value == "call":
        # self-call to external.
        mem_pos = sub
        mem_size = get_size_of_type(sub.typ) * 32
        return LLLnode.from_list(["return", mem_pos, mem_size], typ=sub.typ)

    elif sub.annotation and "Internal Call" in sub.annotation:
        mem_pos = sub.args[-1].value if sub.value == "seq_unchecked" else sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        # Add zero padder if bytes are present in output.
        zero_padder = ["pass"]
        byte_arrays = [
            (i, x) for i, x in enumerate(sub.typ.tuple_members()) if isinstance(x, ByteArrayLike)
        ]
        if byte_arrays:
            i, x = byte_arrays[-1]
            zero_padder = zero_pad(bytez_placeholder=["add", mem_pos, ["mload", mem_pos + i * 32]])
        return LLLnode.from_list(
            ["seq"] + [sub] + [zero_padder] + [make_return_stmt(stmt, context, mem_pos, mem_size)],
            typ=sub.typ,
            pos=getpos(stmt),
            valency=0,
        )

    abi_typ = abi_type_of(context.return_type)
    # according to the ABI, return types are ALWAYS tuples even if
    # only one element is being returned.
    # https://solidity.readthedocs.io/en/latest/abi-spec.html#function-selector-and-argument-encoding
    # "and the return values v_1, ..., v_k of f are encoded as
    #
    #    enc((v_1, ..., v_k))
    #    i.e. the values are combined into a tuple and encoded.
    # "
    # therefore, wrap it in a tuple if it's not already a tuple.
    # (big difference between returning `(bytes,)` and `bytes`.
    abi_typ = ensure_tuple(abi_typ)
    abi_bytes_needed = abi_typ.static_size() + abi_typ.dynamic_size_bound()
    dst, _ = context.memory_allocator.increase_memory(abi_bytes_needed)
    return_buffer = LLLnode(
        dst, location="memory", annotation="return_buffer", typ=context.return_type
    )

    check_assign(return_buffer, sub, pos=getpos(stmt))

    encode_out = abi_encode(return_buffer, sub, pos=getpos(stmt), returns=True)
    load_return_len = ["mload", MemoryPositions.FREE_VAR_SPACE]
    os = [
        "seq",
        ["mstore", MemoryPositions.FREE_VAR_SPACE, encode_out],
        make_return_stmt(stmt, context, return_buffer, load_return_len),
    ]
    return LLLnode.from_list(os, typ=None, pos=getpos(stmt), valency=0)

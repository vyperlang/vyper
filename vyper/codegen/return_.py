from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import getpos
from vyper.types import BaseType
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
    dst = context.memory_allocator.increase_memory(abi_bytes_needed)
    return_buffer = LLLnode(
        dst, location="memory", annotation="return_buffer", typ=context.return_type
    )

    check_assign(return_buffer, sub, pos=getpos(stmt))

    # in case of multi we can't create a variable to store location of the return expression
    # as multi can have data from multiple location like store, calldata etc
    if sub.value == "multi":
        encode_out = abi_encode(return_buffer, sub, pos=getpos(stmt), returns=True)
        load_return_len = ["mload", MemoryPositions.FREE_VAR_SPACE]
        os = [
            "seq",
            ["mstore", MemoryPositions.FREE_VAR_SPACE, encode_out],
            make_return_stmt(stmt, context, return_buffer, load_return_len),
        ]
        return LLLnode.from_list(os, typ=None, pos=getpos(stmt), valency=0)

    # for tuple return types where a function is called inside the tuple, we
    # process the calls prior to encoding the return data
    if sub.value == "seq_unchecked" and sub.args[-1].value == "multi":
        encode_out = abi_encode(return_buffer, sub.args[-1], pos=getpos(stmt), returns=True)
        load_return_len = ["mload", MemoryPositions.FREE_VAR_SPACE]
        os = (
            ["seq"]
            + sub.args[:-1]
            + [
                ["mstore", MemoryPositions.FREE_VAR_SPACE, encode_out],
                make_return_stmt(stmt, context, return_buffer, load_return_len),
            ]
        )
        return LLLnode.from_list(os, typ=None, pos=getpos(stmt), valency=0)

    # for all othe cases we are creating a stack variable named sub_loc to store the  location
    # of the return expression. This is done so that the return expression does not get evaluated
    # abi-encode uses a function named o_list which evaluate the expression multiple times
    sub_loc = LLLnode("sub_loc", typ=sub.typ, location=sub.location)
    encode_out = abi_encode(return_buffer, sub_loc, pos=getpos(stmt), returns=True)
    load_return_len = ["mload", MemoryPositions.FREE_VAR_SPACE]
    os = [
        "with",
        "sub_loc",
        sub,
        [
            "seq",
            ["mstore", MemoryPositions.FREE_VAR_SPACE, encode_out],
            make_return_stmt(stmt, context, return_buffer, load_return_len),
        ],
    ]
    return LLLnode.from_list(os, typ=None, pos=getpos(stmt), valency=0)

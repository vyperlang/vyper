from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import getpos, make_byte_array_copier
from vyper.types import BaseType, is_base_type
from vyper.utils import MemoryPositions, bytes_to_int, keccak256


def keccak256_helper(expr, args, kwargs, context):
    sub = args[0]
    # Can hash literals
    if isinstance(sub, bytes):
        return LLLnode.from_list(
            bytes_to_int(keccak256(sub)), typ=BaseType("bytes32"), pos=getpos(expr)
        )
    # Can hash bytes32 objects
    if is_base_type(sub.typ, "bytes32"):
        return LLLnode.from_list(
            [
                "seq",
                ["mstore", MemoryPositions.FREE_VAR_SPACE, sub],
                ["sha3", MemoryPositions.FREE_VAR_SPACE, 32],
            ],
            typ=BaseType("bytes32"),
            pos=getpos(expr),
        )
    # Copy the data to an in-memory array
    if sub.location == "memory":
        # If we are hashing a value in memory, no need to copy it, just hash in-place
        return LLLnode.from_list(
            ["with", "_sub", sub, ["sha3", ["add", "_sub", 32], ["mload", "_sub"]]],
            typ=BaseType("bytes32"),
            pos=getpos(expr),
        )
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(["sload", ["sha3_32", "_sub"]], typ=BaseType("int128"))
    else:
        # This should never happen, but just left here for future compiler-writers.
        raise Exception(f"Unsupported location: {sub.location}")  # pragma: no test
    placeholder = context.new_placeholder(sub.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=sub.typ, location="memory")
    copier = make_byte_array_copier(
        placeholder_node, LLLnode.from_list("_sub", typ=sub.typ, location=sub.location),
    )
    return LLLnode.from_list(
        ["with", "_sub", sub, ["seq", copier, ["sha3", ["add", placeholder, 32], lengetter]]],
        typ=BaseType("bytes32"),
        pos=getpos(expr),
    )

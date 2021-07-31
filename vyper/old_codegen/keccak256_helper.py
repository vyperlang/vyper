from math import ceil

from vyper.exceptions import CompilerPanic
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_byte_array_copier
from vyper.old_codegen.types import BaseType, ByteArrayLike, is_base_type
from vyper.utils import MemoryPositions, bytes_to_int, keccak256


def _check_byteslike(typ, _expr):
    if not isinstance(typ, ByteArrayLike) and not is_base_type(typ, "bytes32"):
        # NOTE this may be checked at a higher level, but just be safe
        raise CompilerPanic("keccak256 only accepts bytes-like objects",)


def _gas_bound(num_words):
    SHA3_BASE = 30
    SHA3_PER_WORD = 6
    return SHA3_BASE + num_words * SHA3_PER_WORD


def keccak256_helper(expr, lll_args, kwargs, context):
    if len(lll_args) != 1:
        # NOTE this may be checked at a higher level, but just be safe
        raise CompilerPanic("keccak256 must be called with exactly 1 argument", expr)

    sub = lll_args[0]
    _check_byteslike(sub.typ, expr)

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
            add_gas_estimate=_gas_bound(1),
        )

    # type is ByteArrayLike.

    # Otherwise, copy the data to an in-memory buffer
    # TODO refactor the following logic into a function, ensure_in_memory,
    # which elides the byte array copy if the bytes are already in memory.
    if sub.location == "memory":
        # If we are hashing a value in memory, no need to copy it, just hash in-place
        return LLLnode.from_list(
            [
                "with",
                "_buf",
                sub,
                ["with", "_len", ["mload", "_buf"], ["sha3", ["add", "_buf", 32], "_len"]],
            ],
            typ=BaseType("bytes32"),
            pos=getpos(expr),
            add_gas_estimate=_gas_bound(ceil(sub.typ.maxlen / 32)),
        )

    placeholder = context.new_internal_variable(sub.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=sub.typ, location="memory")
    copier = make_byte_array_copier(
        placeholder_node, LLLnode.from_list("_src", typ=sub.typ, location=sub.location),
    )
    return LLLnode.from_list(
        [
            "with",
            "_src",
            sub,
            [
                "with",
                "_dst",
                placeholder_node,
                ["seq", copier, ["sha3", ["add", "_dst", 32], ["mload", "_dst"]]],
            ],
        ],
        typ=BaseType("bytes32"),
        pos=getpos(expr),
        annotation="keccak256",
        add_gas_estimate=_gas_bound(ceil(sub.typ.maxlen / 32)),
    )

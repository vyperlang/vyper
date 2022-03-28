from math import ceil

from vyper.codegen.core import ensure_in_memory
from vyper.codegen.ir_node import IRnode
from vyper.codegen.types import BaseType, ByteArrayLike, is_base_type
from vyper.exceptions import CompilerPanic
from vyper.utils import MemoryPositions, bytes_to_int, keccak256


def _check_byteslike(typ, _expr):
    if not isinstance(typ, ByteArrayLike) and not is_base_type(typ, "bytes32"):
        # NOTE this may be checked at a higher level, but just be safe
        raise CompilerPanic(
            "keccak256 only accepts bytes-like objects",
        )


def _gas_bound(num_words):
    SHA3_BASE = 30
    SHA3_PER_WORD = 6
    return SHA3_BASE + num_words * SHA3_PER_WORD


def keccak256_helper(expr, ir_arg, context):
    sub = ir_arg  # TODO get rid of useless variable
    _check_byteslike(sub.typ, expr)

    # Can hash literals
    # TODO this is dead code.
    if isinstance(sub, bytes):
        return IRnode.from_list(bytes_to_int(keccak256(sub)), typ=BaseType("bytes32"))

    # Can hash bytes32 objects
    if is_base_type(sub.typ, "bytes32"):
        return IRnode.from_list(
            [
                "seq",
                ["mstore", MemoryPositions.FREE_VAR_SPACE, sub],
                ["sha3", MemoryPositions.FREE_VAR_SPACE, 32],
            ],
            typ=BaseType("bytes32"),
            add_gas_estimate=_gas_bound(1),
        )

    sub = ensure_in_memory(sub, context)

    return IRnode.from_list(
        [
            "with",
            "_buf",
            sub,
            ["sha3", ["add", "_buf", 32], ["mload", "_buf"]],
        ],
        typ=BaseType("bytes32"),
        annotation="keccak256",
        add_gas_estimate=_gas_bound(ceil(sub.typ.maxlen / 32)),
    )

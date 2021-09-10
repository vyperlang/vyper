import functools
import uuid

from vyper.evm.opcodes import version_check
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.types.types import (
    ByteArrayLike,
    ListType,
    get_size_of_type,
    is_base_type,
)
from vyper.utils import MemoryPositions


def _shr(x, bits):
    if version_check(begin="constantinople"):
        return ["shr", x, bits]
    return ["div", x, ["pow", 2, bits]]


def _sar(x, bits):
    if version_check(begin="constantinople"):
        return ["sar", x, bits]
    return ["sdiv", x, ["pow", 2, bits]]


def address_clamp(lll_node):
    if version_check(begin="constantinople"):
        return ["assert", ["iszero", ["shr", 160, lll_node]]]
    else:
        return ["uclamplt", lll_node, ["mload", MemoryPositions.ADDRSIZE]]


def int128_clamp(lll_node):
    if version_check(begin="constantinople"):
        return [
            "with",
            "_val",
            lll_node,
            [
                "seq",
                # if _val is in bounds,
                # _val >>> 127 == 0 for positive _val
                # _val >>> 127 == -1 for negative _val
                # -1 and 0 are the only numbers which are unchanged by sar,
                # so sar'ing (_val>>>127) one more bit should leave it unchanged.
                ["assert", ["eq", ["sar", 128, "_val"], ["sar", 127, "_val"]]],
                "_val",
            ],
        ]
    else:
        return [
            "clamp",
            ["mload", MemoryPositions.MIN_INT128],
            lll_node,
            ["mload", MemoryPositions.MAX_INT128],
        ]

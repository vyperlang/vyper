import functools
import uuid

from vyper.opcodes import version_check
from vyper.parser.lll_node import LLLnode
from vyper.types.types import (
    ByteArrayLike,
    ListType,
    get_size_of_type,
    is_base_type,
)
from vyper.utils import MemoryPositions


def _mk_calldatacopy_copier(pos, sz, mempos):
    return ["calldatacopy", mempos, ["add", 4, pos], sz]


def _mk_codecopy_copier(pos, sz, mempos):
    return ["codecopy", mempos, ["add", "~codelen", pos], sz]


def make_arg_clamper(datapos, mempos, typ, is_init=False):
    """
    Clamps argument to type limits.

    Arguments
    ---------
    datapos : int | LLLnode
        Calldata offset of the value being clamped
    mempos : int | LLLnode
        Memory offset that the value is stored at during clamping
    typ : vyper.types.types.BaseType
        Type of the value
    is_init : bool, optional
        Boolean indicating if we are generating init bytecode

    Returns
    -------
    LLLnode
        Arg clamper LLL
    """

    if not is_init:
        data_decl = ["calldataload", ["add", 4, datapos]]
        copier = functools.partial(_mk_calldatacopy_copier, mempos=mempos)
    else:
        data_decl = ["codeload", ["add", "~codelen", datapos]]
        copier = functools.partial(_mk_codecopy_copier, mempos=mempos)
    # Numbers: make sure they're in range
    if is_base_type(typ, "int128"):
        return LLLnode.from_list(
            int128_clamp(data_decl), typ=typ, annotation="checking int128 input"
        )
    # Booleans: make sure they're zero or one
    elif is_base_type(typ, "bool"):
        if version_check(begin="constantinople"):
            lll = ["assert", ["iszero", ["shr", 1, data_decl]]]
        else:
            lll = ["uclamplt", data_decl, 2]
        return LLLnode.from_list(lll, typ=typ, annotation="checking bool input")
    # Addresses: make sure they're in range
    elif is_base_type(typ, "address"):
        if version_check(begin="constantinople"):
            lll = ["assert", ["iszero", ["shr", 160, data_decl]]]
        else:
            lll = ["uclamplt", data_decl, ["mload", MemoryPositions.ADDRSIZE]]
        return LLLnode.from_list(lll, typ=typ, annotation="checking address input")
    # Bytes: make sure they have the right size
    elif isinstance(typ, ByteArrayLike):
        return LLLnode.from_list(
            [
                "seq",
                copier(data_decl, 32 + typ.maxlen),
                ["assert", ["le", ["calldataload", ["add", 4, data_decl]], typ.maxlen]],
            ],
            typ=None,
            annotation="checking bytearray input",
        )
    # Lists: recurse
    elif isinstance(typ, ListType):
        if typ.count > 5 or (type(datapos) is list and type(mempos) is list):
            # find ultimate base type
            subtype = typ.subtype
            while hasattr(subtype, "subtype"):
                subtype = subtype.subtype

            # make arg clamper for the base type
            offset = MemoryPositions.FREE_LOOP_INDEX
            clamper = make_arg_clamper(
                ["add", datapos, ["mload", offset]],
                ["add", mempos, ["mload", offset]],
                subtype,
                is_init,
            )
            if clamper.value == "pass":
                # no point looping if the base type doesn't require clamping
                return clamper

            # loop the entire array at once, even if it's multidimensional
            type_size = get_size_of_type(typ)
            i_incr = get_size_of_type(subtype) * 32

            mem_to = type_size * 32
            loop_label = f"_check_list_loop_{str(uuid.uuid4())}"

            lll_node = [
                ["mstore", offset, 0],  # init loop
                ["label", loop_label],
                clamper,
                ["mstore", offset, ["add", ["mload", offset], i_incr]],
                ["if", ["lt", ["mload", offset], mem_to], ["goto", loop_label]],
            ]
        else:
            lll_node = []
            for i in range(typ.count):
                offset = get_size_of_type(typ.subtype) * 32 * i
                lll_node.append(
                    make_arg_clamper(datapos + offset, mempos + offset, typ.subtype, is_init)
                )
        return LLLnode.from_list(["seq"] + lll_node, typ=None, annotation="checking list input")
    # Otherwise don't make any checks
    else:
        return LLLnode.from_list("pass")


def int128_clamp(lll_node):
    if version_check(begin="constantinople"):
        return [
            "with",
            "_val",
            lll_node,
            [
                "seq_unchecked",
                ["dup1", "_val"],
                ["if", ["slt", "_val", 0], ["not", "pass"]],
                ["assert", ["iszero", ["shr", 127, "pass"]]],
            ],
        ]
    else:
        return [
            "clamp",
            ["mload", MemoryPositions.MINNUM],
            lll_node,
            ["mload", MemoryPositions.MAXNUM],
        ]

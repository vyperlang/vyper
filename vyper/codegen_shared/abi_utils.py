"""
Shared ABI encoding utilities used by both codegen pipelines.

If codegen_legacy is removed, consider moving these to vyper/abi.py
or into methods on VyperType / ABIType.
"""

from vyper.semantics.types import (
    DArrayT,
    StructT,
    TupleT,
    VyperType,
    _BytestringT,
    is_unbounded_sequence_type,
)
from vyper.semantics.types.subscriptable import SArrayT

DYNAMIC_ARRAY_OVERHEAD = 1


def is_tuple_like(typ: VyperType) -> bool:
    """Check if type is tuple-like (tuple or struct)."""
    # A lot of code paths treat tuples and structs similarly
    # so we have a convenience function to detect it
    ret = isinstance(typ, (TupleT, StructT))
    assert ret == hasattr(typ, "tuple_items")
    return ret


def needs_external_call_wrap(typ: VyperType) -> bool:
    """
    For calls to ABI conforming contracts, return types are ALWAYS tuples
    even if only one element is being returned.
    https://docs.soliditylang.org/en/latest/abi-spec.html#function-selector-and-argument-encoding
    """
    return not (isinstance(typ, TupleT) and typ.length > 1)


def calculate_type_for_external_return(typ: VyperType) -> VyperType:
    """Wrap type in a tuple if needed for ABI return encoding."""
    if needs_external_call_wrap(typ):
        return TupleT((typ,))
    return typ


def abi_encoding_matches_vyper(typ: VyperType) -> bool:
    """
    Returns True if the ABI encoding matches vyper's memory encoding
    of a type, otherwise False.
    """
    return not typ.abi_type.is_dynamic()


def has_length_word(typ):
    # Consider moving this to an attribute on typ
    return isinstance(typ, (DArrayT, _BytestringT))


def punnable(src_typ, dst_typ):
    """
    Return True if memory laid out as `src_typ` can be read (punned) as `dst_typ`.

    Compatible types can differ in element or member layout, e.g.
    DynArray[Bytes[10], 5] vs DynArray[Bytes[512], 5] (element stride 64
    vs 544). A wider bytestring bound or DynArray capacity at the top level
    does not change the layout of the data that is present.
    """
    if isinstance(dst_typ, (DArrayT, SArrayT)):
        assert isinstance(src_typ, (DArrayT, SArrayT))
        pairs = [(src_typ.value_type, dst_typ.value_type)]
    elif isinstance(dst_typ, TupleT):
        assert isinstance(src_typ, TupleT)
        n = len(dst_typ.member_types)
        assert len(src_typ.member_types) == n
        pairs = [(src_typ.member_types[i], dst_typ.member_types[i]) for i in range(n)]
    else:
        # primitive words, bytestrings ([length][data]) and (nominal) structs
        return True

    # nested values also need equal sizes: they determine strides and offsets
    return all(_punnable_nested(s, d) for s, d in pairs)


def _punnable_nested(src_typ, dst_typ):
    # an unbounded element or member is a pointer cell holding a payload
    # pointer, not the value. A cell is never interchangeable with an inline
    # value, even when the inline value's size happens to equal the cell's,
    # and a cell is read as the payload type it was written for.
    src_cell = is_unbounded_sequence_type(src_typ)
    dst_cell = is_unbounded_sequence_type(dst_typ)
    if src_cell or dst_cell:
        return src_cell and dst_cell and src_typ == dst_typ
    return src_typ.memory_bytes_required == dst_typ.memory_bytes_required and punnable(
        src_typ, dst_typ
    )

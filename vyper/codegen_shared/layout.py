"""
Shared type layout helpers used by both codegen pipelines.
"""

from vyper.semantics.types import DArrayT, TupleT, _BytestringT, is_unbounded_sequence_type
from vyper.semantics.types.subscriptable import SArrayT

DYNAMIC_ARRAY_OVERHEAD = 1


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

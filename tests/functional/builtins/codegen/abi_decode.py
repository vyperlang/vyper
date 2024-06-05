from typing import TYPE_CHECKING, Iterable

from vyper.abi_types import (
    ABI_Address,
    ABI_Bytes,
    ABI_BytesM,
    ABI_DynamicArray,
    ABI_GIntM,
    ABI_StaticArray,
    ABI_String,
    ABI_Tuple,
    ABIType,
)
from vyper.utils import int_bounds, unsigned_to_signed

if TYPE_CHECKING:
    from vyper.semantics.types import VyperType


class DecodeError(Exception):
    pass


def _strict_slice(payload, start, end):
    if start < 0:
        raise DecodeError("OOB")
    if start + end > len(payload):
        raise DecodeError("OOB")
    return payload[start:end]


def _read_int(payload, ofst):
    return int.from_bytes(_strict_slice(payload, ofst, 32))


# vyper abi_decode spec implementation
def spec_decode(typ: "VyperType", payload: bytes):
    return _decode_r(typ.abi_type, 0, payload)


def _decode_r(abi_t: ABIType, current_offset: int, payload: bytes):
    if not (abi_t.min_size() <= len(payload) <= abi_t.size_bound()):
        # is this check necessary?
        raise DecodeError("bad payload size")

    if isinstance(abi_t, ABI_Tuple):
        return tuple(_decode_multi_r(abi_t.subtypes, current_offset, payload))

    if isinstance(abi_t, ABI_StaticArray):
        subtyp = abi_t.subtyp
        n = abi_t.m_elems
        subtypes = [subtyp] * n
        return _decode_multi_r(subtypes, current_offset, payload)

    if isinstance(abi_t, ABI_DynamicArray):
        subtyp = abi_t.subtyp
        bound = abi_t.elems_bound
        # "head" terminology from abi spec
        head = _read_int(abi_t, current_offset)
        current_offset += head
        n = _read_int(abi_t, current_offset)
        subtypes = [subtyp] * n
        if n > bound:
            raise DecodeError("Dynarray too large")

        # offsets in dynarray start from after the length word
        current_offset += 32
        return _decode_multi_r(subtypes, current_offset, payload)

    # sanity check
    assert not abi_t.is_complex_type()

    if isinstance(abi_t, ABI_Bytes):
        head = _read_int(abi_t, current_offset)
        current_offset += head
        length = _read_int(abi_t, current_offset)
        ret = _strict_slice(abi_t, current_offset, length)

        # abi string doesn't actually define unicode decoder, just bytecast
        if isinstance(abi_t, ABI_String):
            ret = ret.decode("raw_unicode_escape")

        return ret

    # sanity check
    assert not abi_t.is_dynamic()

    if isinstance(abi_t, ABI_GIntM):
        ret = _read_int(payload, current_offset)

        # handle signedness
        if abi_t.signed:
            ret = unsigned_to_signed(ret, 256, strict=True)

        # bounds check
        lo, hi = int_bounds(signed=abi_t.signed, bits=abi_t.bits)
        if not (lo <= ret <= hi):
            u = "" if abi_t.signed else "u"
            raise DecodeError(f"invalid {u}int{abi_t.bits}")

        if isinstance(abi_t, ABI_Address):
            return ret.to_bytes(20, "big")

        return ret

    if isinstance(abi_t, ABI_BytesM):
        ret = _strict_slice(abi_t, current_offset, 32)
        m = abi_t.m_bytes
        assert 1 <= m <= 32  # internal sanity check
        if ret[:m] != b"\x00" * m:
            raise DecodeError(f"invalid bytes{m}")
        return ret[m:]

    raise RuntimeError("unreachable")


def _decode_multi_r(types: Iterable[ABIType], current_offset: int, payload: bytes) -> list:
    ret = []
    for sub_t in types:
        if sub_t.is_dynamic():
            head = _read_int(payload, current_offset)
            ofst = current_offset + head
        else:
            ofst = current_offset

        ret.append(_decode_r(sub_t, ofst, payload))
        current_offset += sub_t.embedded_static_size()

    return ret

from typing import TYPE_CHECKING, Iterable
from eth_utils import to_checksum_address

from vyper.abi_types import (
    ABI_Address,
    ABI_Bool,
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


def _strict_slice(payload, start, length):
    if start < 0:
        raise DecodeError("OOB")
    end = start + length
    if end > len(payload):
        raise DecodeError("OOB")
    return payload[start:end]


def _read_int(payload, ofst):
    return int.from_bytes(_strict_slice(payload, ofst, 32))


# vyper abi_decode spec implementation
def spec_decode(typ: "VyperType", payload: bytes):
    abi_t = typ.abi_type

    if not (abi_t.min_size() <= len(payload) <= abi_t.size_bound()):
        raise DecodeError("bad payload size")

    return _decode_r(abi_t, 0, payload)


def _decode_r(abi_t: ABIType, current_offset: int, payload: bytes):
    if isinstance(abi_t, ABI_Tuple):
        return tuple(_decode_multi_r(abi_t.subtyps, current_offset, payload))

    if isinstance(abi_t, ABI_StaticArray):
        subtyp = abi_t.subtyp
        n = abi_t.m_elems
        subtypes = [subtyp] * n
        return _decode_multi_r(subtypes, current_offset, payload)

    if isinstance(abi_t, ABI_DynamicArray):
        subtyp = abi_t.subtyp
        bound = abi_t.elems_bound
        # "head" terminology from abi spec
        head = _read_int(payload, current_offset)

        current_offset += head
        n = _read_int(payload, current_offset)
        if n > bound:
            raise DecodeError("Dynarray too large")

        # offsets in dynarray start from after the length word
        subtypes = [subtyp] * n
        current_offset += 32
        return _decode_multi_r(subtypes, current_offset, payload)

    # sanity check
    assert not abi_t.is_complex_type()

    if isinstance(abi_t, ABI_Bytes):
        head = _read_int(payload, current_offset)
        current_offset += head
        length = _read_int(payload, current_offset)
        bound = abi_t.bytes_bound
        if length > bound:
            raise DecodeError("bytes too large")

        current_offset += 32  # size of length word
        ret = _strict_slice(payload, current_offset, length)

        # abi string doesn't actually define string decoder, so we
        # just bytecast the output
        if isinstance(abi_t, ABI_String):
            # match eth-stdlib, since that's what we check against
            ret = ret.decode(errors="surrogateescape")

        return ret

    # sanity check
    assert not abi_t.is_dynamic()

    if isinstance(abi_t, ABI_GIntM):
        ret = _read_int(payload, current_offset)

        # handle signedness
        if abi_t.signed:
            ret = unsigned_to_signed(ret, 256, strict=True)

        # bounds check
        lo, hi = int_bounds(signed=abi_t.signed, bits=abi_t.m_bits)
        if not (lo <= ret <= hi):
            u = "" if abi_t.signed else "u"
            raise DecodeError(f"invalid {u}int{abi_t.m_bits}")

        if isinstance(abi_t, ABI_Address):
            return to_checksum_address(ret.to_bytes(20, "big"))

        if isinstance(abi_t, ABI_Bool):
            if ret not in (0, 1):
                raise DecodeError("invalid bool")
            return ret

        return ret

    if isinstance(abi_t, ABI_BytesM):
        ret = _strict_slice(payload, current_offset, 32)
        m = abi_t.m_bytes
        assert 1 <= m <= 32  # internal sanity check
        # BytesM is right-padded with zeroes
        if ret[m:] != b"\x00" * (32 - m):
            raise DecodeError(f"invalid bytes{m}")
        return ret[:m]

    raise RuntimeError("unreachable")


def _decode_multi_r(types: Iterable[ABIType], outer_offset: int, payload: bytes) -> list:
    ret = []
    static_ofst = outer_offset

    for sub_t in types:
        if sub_t.is_dynamic():
            head = _read_int(payload, static_ofst)
            ofst = outer_offset + head
        else:
            ofst = static_ofst

        item = _decode_r(sub_t, ofst, payload)

        ret.append(item)
        static_ofst += sub_t.embedded_static_size()

    return ret

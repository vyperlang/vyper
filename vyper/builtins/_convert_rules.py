"""
Backend-independent validation rules for ``convert()``.

Keeping type-pair validation in semantic analysis ensures that both the
legacy and direct-to-Venom pipelines accept and reject the same programs.
Value-dependent checks remain in code generation.
"""

from vyper.exceptions import StructureException, TypeMismatch
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DecimalT,
    FlagT,
    IntegerT,
    StringT,
    _BytestringT,
    is_bounded_length,
)
from vyper.semantics.types.shortcuts import UINT256_T

_ALLOWED_CONVERSIONS: dict[type, tuple[type, ...]] = {
    BoolT: (IntegerT, DecimalT, BytesM_T, AddressT, BoolT, BytesT, StringT),
    AddressT: (BytesM_T, IntegerT, BytesT),
    IntegerT: (IntegerT, DecimalT, BytesM_T, AddressT, BoolT, FlagT, BytesT),
    DecimalT: (IntegerT, BoolT, BytesM_T, BytesT),
    BytesM_T: (IntegerT, DecimalT, BytesM_T, AddressT, BytesT, BoolT, FlagT),
    BytesT: (StringT, BytesT),
    StringT: (BytesT, StringT),
    FlagT: (IntegerT,),
}


def _fail(input_type, output_type, node=None):
    raise TypeMismatch(f"Can't convert {input_type} to {output_type}", node)


def validate_convertibility(input_type, output_type, node=None):
    allowed = _ALLOWED_CONVERSIONS.get(type(output_type))
    if allowed is None:
        raise StructureException(f"Conversion to {output_type} is invalid.", node)

    if not isinstance(input_type, allowed):
        _fail(input_type, output_type, node)

    if isinstance(input_type, _BytestringT) and not isinstance(output_type, _BytestringT):
        # Bounded bytestrings which cannot fit in the output word are invalid
        # statically. Unbounded inputs are checked against their runtime length.
        max_bytes = output_type.m if isinstance(output_type, BytesM_T) else 32
        if is_bounded_length(input_type.maxlen) and input_type.maxlen > max_bytes:
            _fail(input_type, output_type, node)

    if isinstance(output_type, _BytestringT):
        # Widening within the same bytestring class is already an assignment,
        # not a conversion. The generic subtype check handles INF targets.
        if (
            isinstance(input_type, type(output_type))
            and is_bounded_length(input_type.maxlen)
            and is_bounded_length(output_type.maxlen)
            and input_type.maxlen <= output_type.maxlen
        ):
            _fail(input_type, output_type, node)

    # Flags convert to uint256 and bytes32, and only uint256 converts to a flag.
    if isinstance(input_type, FlagT):
        if output_type != UINT256_T and not (
            isinstance(output_type, BytesM_T) and output_type.m == 32
        ):
            _fail(input_type, output_type, node)
    if isinstance(output_type, FlagT) and input_type != UINT256_T:
        _fail(input_type, output_type, node)

    # Addresses are unsigned.
    if (
        isinstance(input_type, AddressT)
        and isinstance(output_type, IntegerT)
        and output_type.is_signed
    ):
        _fail(input_type, output_type, node)
    if (
        isinstance(input_type, IntegerT)
        and input_type.is_signed
        and isinstance(output_type, AddressT)
    ):
        _fail(input_type, output_type, node)

    # Narrowing numeric/address conversions to bytesM have no runtime clamp.
    if isinstance(output_type, BytesM_T):
        if isinstance(input_type, (IntegerT, DecimalT)) and output_type.m_bits < input_type.bits:
            _fail(input_type, output_type, node)
        if isinstance(input_type, AddressT) and output_type.m_bits < 160:
            _fail(input_type, output_type, node)

"""
Backend-independent validation rules for ``convert()``.

Keeping type-pair validation in semantic analysis ensures that both the
legacy and direct-to-Venom pipelines accept and reject the same programs.
Value-dependent checks remain in code generation.
"""

from typing import Callable

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
    VyperType,
    is_bounded_length,
)
from vyper.semantics.types.shortcuts import UINT256_T

# output class -> input classes; valid for every instance of those classes.
_ALLOWED_CONVERSIONS: dict[type, tuple[type, ...]] = {
    BoolT: (IntegerT, DecimalT, BytesM_T, AddressT, BoolT),
    AddressT: (BytesM_T,),
    IntegerT: (IntegerT, DecimalT, BytesM_T, BoolT),
    DecimalT: (IntegerT, BoolT, BytesM_T),
    BytesM_T: (BytesM_T, BoolT),
    BytesT: (StringT, BytesT),
    StringT: (BytesT, StringT),
    FlagT: (),
}


def _fits_word(input_type, output_type):
    # Bounded bytestrings which cannot fit in the output word are invalid
    # statically. Unbounded inputs are checked against their runtime length.
    max_bytes = output_type.m if isinstance(output_type, BytesM_T) else 32
    return not is_bounded_length(input_type.maxlen) or input_type.maxlen <= max_bytes


def _fits_bytesm(input_type, output_type):
    # Narrowing numeric conversions to bytesM have no runtime clamp.
    return output_type.m_bits >= input_type.bits


def _address_fits_bytesm(input_type, output_type):
    return output_type.m_bits >= 160


def _unsigned_output(input_type, output_type):
    return not output_type.is_signed


def _unsigned_input(input_type, output_type):
    return not input_type.is_signed


def _output_is_uint256(input_type, output_type):
    return output_type == UINT256_T


def _output_is_bytes32(input_type, output_type):
    return output_type.m == 32


def _input_is_uint256(input_type, output_type):
    return input_type == UINT256_T


# (input class, output classes, predicate); additional conversions which are
# valid only for some instances of those classes.
_CONDITIONAL_CONVERSIONS: list[
    tuple[type, type | tuple[type, ...], Callable[[VyperType, VyperType], bool]]
] = [
    (BytesT, (BoolT, AddressT, IntegerT, DecimalT, BytesM_T), _fits_word),
    (StringT, BoolT, _fits_word),
    (IntegerT, BytesM_T, _fits_bytesm),
    (DecimalT, BytesM_T, _fits_bytesm),
    (AddressT, BytesM_T, _address_fits_bytesm),
    # Addresses are unsigned.
    (AddressT, IntegerT, _unsigned_output),
    (IntegerT, AddressT, _unsigned_input),
    # Flags convert to uint256 and bytes32, and only uint256 converts to a flag.
    (FlagT, IntegerT, _output_is_uint256),
    (FlagT, BytesM_T, _output_is_bytes32),
    (IntegerT, FlagT, _input_is_uint256),
]


def validate_convertibility(input_type, output_type, node=None):
    allowed = _ALLOWED_CONVERSIONS.get(type(output_type))
    if allowed is None:
        raise StructureException(f"Conversion to {output_type} is invalid.", node)

    # Same-class identity/widening bytestring conversions are already
    # rejected by the subtype check in Convert.infer_arg_types.
    if isinstance(input_type, allowed):
        return

    for input_cls, output_cls, predicate in _CONDITIONAL_CONVERSIONS:
        if isinstance(input_type, input_cls) and isinstance(output_type, output_cls):
            if predicate(input_type, output_type):
                return

    raise TypeMismatch(f"Can't convert {input_type} to {output_type}", node)

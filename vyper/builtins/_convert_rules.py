"""
Backend-independent validation rules for ``convert()``.

Keeping type-pair validation in semantic analysis ensures that both the
legacy and direct-to-Venom pipelines accept and reject the same programs.
Value-dependent checks remain in code generation.
"""

from typing import Any, Callable

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


# (input class, output classes, predicate); additional conversions which are
# valid only for some instances of those classes.
_CONDITIONAL_CONVERSIONS: list[tuple[type, type | tuple[type, ...], Callable[[Any, Any], bool]]] = [
    (BytesT, (BoolT, AddressT, IntegerT, DecimalT, BytesM_T), _fits_word),
    (StringT, BoolT, _fits_word),
    (IntegerT, BytesM_T, _fits_bytesm),
    (DecimalT, BytesM_T, _fits_bytesm),
    (AddressT, BytesM_T, lambda i, o: o.m_bits >= 160),
    # Addresses are unsigned.
    (AddressT, IntegerT, lambda i, o: not o.is_signed),
    (IntegerT, AddressT, lambda i, o: not i.is_signed),
    # Flags convert to uint256 and bytes32, and only uint256 converts to a flag.
    (FlagT, IntegerT, lambda i, o: o == UINT256_T),
    (FlagT, BytesM_T, lambda i, o: o.m == 32),
    (IntegerT, FlagT, lambda i, o: i == UINT256_T),
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

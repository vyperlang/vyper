"""
Shared `convert()` rules: which conversions are legal, and the numeric
bounds used to clamp conversion inputs.

This is the single source of truth for both codegen backends (legacy
`vyper/builtins/_convert.py` and venom-direct
`vyper/codegen_venom/builtins/convert.py`). Keeping the conversion
matrix in one backend-neutral module prevents the two pipelines from
diverging on which programs are valid (GH 4987, GH 5019, GH 5111).

This module must not import from either codegen package.
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
)
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.utils import evm_div

# allowed input type classes, keyed by output type class
_ALLOWED_CONVERSIONS: dict[type, tuple[type, ...]] = {
    BoolT: (IntegerT, DecimalT, BytesM_T, AddressT, BoolT, BytesT, StringT),
    AddressT: (BytesM_T, IntegerT, BytesT),
    IntegerT: (IntegerT, DecimalT, BytesM_T, AddressT, BoolT, FlagT, BytesT),
    DecimalT: (IntegerT, BoolT, BytesM_T, BytesT),
    BytesM_T: (IntegerT, DecimalT, BytesM_T, AddressT, BytesT, BoolT),
    BytesT: (StringT, BytesT),
    StringT: (BytesT, StringT),
    FlagT: (IntegerT,),
}


def _fail(in_typ, out_typ, node=None):
    raise TypeMismatch(f"Can't convert {in_typ} to {out_typ}", node)


def validate_convertibility(in_typ, out_typ, node=None):
    """
    Validate that `convert(<in_typ>, <out_typ>)` is a legal conversion,
    raising TypeMismatch (or StructureException for unsupported target
    types) otherwise.

    Only rules which are pure functions of the type pair live here;
    value-dependent rules (e.g. literal range checks) stay in codegen.
    """
    allowed = _ALLOWED_CONVERSIONS.get(type(out_typ))
    if allowed is None:
        raise StructureException(f"Conversion to {out_typ} is invalid.", node)

    if not isinstance(in_typ, allowed):
        _fail(in_typ, out_typ, node)

    if isinstance(in_typ, _BytestringT) and not isinstance(out_typ, _BytestringT):
        # bytestring inputs must fit in the output word
        max_bytes = out_typ.m if isinstance(out_typ, BytesM_T) else 32
        if in_typ.maxlen > max_bytes:
            _fail(in_typ, out_typ, node)

    if isinstance(out_typ, _BytestringT):
        # widening a bytestring within the same class is not a real
        # conversion -- the assignment is already legal without convert()
        if isinstance(in_typ, type(out_typ)) and in_typ.maxlen <= out_typ.maxlen:
            _fail(in_typ, out_typ, node)

    # flags only convert to and from uint256
    if isinstance(in_typ, FlagT) and out_typ != UINT256_T:
        _fail(in_typ, out_typ, node)
    if isinstance(out_typ, FlagT) and in_typ != UINT256_T:
        _fail(in_typ, out_typ, node)

    # addresses are unsigned
    if isinstance(in_typ, AddressT) and isinstance(out_typ, IntegerT) and out_typ.is_signed:
        _fail(in_typ, out_typ, node)
    if isinstance(in_typ, IntegerT) and in_typ.is_signed and isinstance(out_typ, AddressT):
        _fail(in_typ, out_typ, node)

    # narrowing conversions to bytesM are blocked (no runtime clamp)
    if isinstance(out_typ, BytesM_T):
        if isinstance(in_typ, (IntegerT, DecimalT)) and out_typ.m_bits < in_typ.bits:
            _fail(in_typ, out_typ, node)
        if isinstance(in_typ, AddressT) and out_typ.m_bits < 160:
            _fail(in_typ, out_typ, node)


def int_to_fixed_clamp_bounds(out_typ: DecimalT) -> tuple[int, int]:
    """
    Inclusive bounds on an integer input such that `input * out_typ.divisor`
    stays within `out_typ`'s representable range.

    Note truncating (not floor) division: flooring the negative bound
    admits one extra value whose scaled result lands below the output
    type's lower bound (GH 5110).
    """
    out_lo, out_hi = out_typ.int_bounds
    divisor = out_typ.divisor
    return evm_div(out_lo, divisor), evm_div(out_hi, divisor)


def fixed_to_int_clamp_bounds(in_typ: DecimalT, out_typ: IntegerT) -> tuple[int, int]:
    """
    Inclusive bounds (in `in_typ`'s fixed-point representation) on a
    decimal input such that truncation to integer lands within `out_typ`.
    """
    out_lo, out_hi = out_typ.int_bounds
    divisor = in_typ.divisor
    return out_lo * divisor, out_hi * divisor

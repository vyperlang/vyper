"""
Numeric bounds shared by `convert()` lowering backends.

These helpers are value-level codegen details. Type-pair legality is
validated by the `convert` builtin during typechecking.
"""

from vyper.semantics.types import DecimalT, IntegerT
from vyper.utils import evm_div


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

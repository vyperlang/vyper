"""
Safe arithmetic operations with overflow/underflow checking.

Extracted from expr.py and stmt.py to eliminate duplication.
Used for binary operations and augmented assignment.
"""
from __future__ import annotations

from typing import Optional, Union

from vyper.codegen.arithmetic import calculate_largest_base, calculate_largest_power
from vyper.exceptions import CompilerPanic, TypeCheckFailure
from vyper.semantics.types import DecimalT, IntegerT
from vyper.venom.basicblock import IRLiteral, IROperand
from vyper.venom.builder import VenomBuilder


def safe_add(
    b: VenomBuilder, x: IROperand, y: IROperand, typ: Union[IntegerT, DecimalT]
) -> IROperand:
    """Add with overflow checking."""
    res: IROperand = b.add(x, y)

    if isinstance(typ, (IntegerT, DecimalT)) and typ.bits < 256:
        return clamp_basetype(b, res, typ)

    # 256-bit overflow check
    if isinstance(typ, (IntegerT, DecimalT)):
        if typ.is_signed:
            # (y < 0) == (res < x)
            y_neg = b.slt(y, IRLiteral(0))
            res_lt_x = b.slt(res, x)
            ok = b.eq(y_neg, res_lt_x)
        else:
            # res >= x
            ok = b.iszero(b.lt(res, x))
        with b.error_context("safeadd"):
            b.assert_(ok)

    return res


def safe_sub(
    b: VenomBuilder, x: IROperand, y: IROperand, typ: Union[IntegerT, DecimalT]
) -> IROperand:
    """Subtract with overflow checking."""
    res: IROperand = b.sub(x, y)

    if isinstance(typ, (IntegerT, DecimalT)) and typ.bits < 256:
        return clamp_basetype(b, res, typ)

    # 256-bit overflow check
    if isinstance(typ, (IntegerT, DecimalT)):
        if typ.is_signed:
            # (y < 0) == (res > x)
            y_neg = b.slt(y, IRLiteral(0))
            res_gt_x = b.sgt(res, x)
            ok = b.eq(y_neg, res_gt_x)
        else:
            # res <= x
            ok = b.iszero(b.gt(res, x))
        with b.error_context("safesub"):
            b.assert_(ok)

    return res


def safe_mul(
    b: VenomBuilder, x: IROperand, y: IROperand, typ: Union[IntegerT, DecimalT]
) -> IROperand:
    """Multiply with overflow checking."""
    res: IROperand = b.mul(x, y)

    if isinstance(typ, (IntegerT, DecimalT)):
        is_signed = typ.is_signed

        if typ.bits > 128:
            # Check overflow mod 256: (res / y == x) OR (y == 0)
            DIV = b.sdiv if is_signed else b.div
            div_check = b.eq(DIV(res, y), x)
            y_zero = b.iszero(y)
            ok = b.or_(div_check, y_zero)

            # int256 special case: not (x == -2^255 and y == -1)
            if is_signed and typ.bits == 256:
                min_int = 1 << 255  # -2^255 in two's complement
                x_is_min = b.eq(x, IRLiteral(min_int))
                y_is_neg1 = b.iszero(b.not_(y))
                special_case = b.and_(x_is_min, y_is_neg1)
                not_special = b.iszero(special_case)
                ok = b.and_(ok, not_special)

            with b.error_context("safemul"):
                b.assert_(ok)

        # For decimals, divide result by divisor
        if isinstance(typ, DecimalT):
            DIV = b.sdiv if is_signed else b.div
            res = DIV(res, IRLiteral(typ.divisor))

        # Clamp result if needed
        if typ.bits < 256 or isinstance(typ, DecimalT):
            res = clamp_basetype(b, res, typ)

    return res


def safe_div(b: VenomBuilder, x: IROperand, y: IROperand, typ: DecimalT) -> IROperand:
    """Decimal division with overflow checking."""
    if not isinstance(typ, DecimalT):
        raise CompilerPanic("/ operator only valid for decimals")

    # Multiply numerator by divisor first
    x_scaled = b.mul(x, IRLiteral(typ.divisor))

    # Clamp divisor > 0 for unsigned, or use sgt for signed
    if typ.is_signed:
        y_gt_zero = b.sgt(y, IRLiteral(0))
    else:
        y_gt_zero = b.gt(y, IRLiteral(0))
    with b.error_context("safediv"):
        b.assert_(y_gt_zero)

    DIV = b.sdiv if typ.is_signed else b.div
    res = DIV(x_scaled, y)

    # Always clamp decimals
    return clamp_basetype(b, res, typ)


def safe_floordiv(b: VenomBuilder, x: IROperand, y: IROperand, typ: IntegerT) -> IROperand:
    """Integer floor division with overflow checking."""
    if not isinstance(typ, IntegerT):
        raise CompilerPanic("// operator only valid for integers")

    is_signed = typ.is_signed

    # Clamp divisor > 0
    if is_signed:
        y_gt_zero = b.sgt(y, IRLiteral(0))
    else:
        y_gt_zero = b.gt(y, IRLiteral(0))
    with b.error_context("safediv"):
        b.assert_(y_gt_zero)

    DIV = b.sdiv if is_signed else b.div
    res: IROperand = DIV(x, y)

    # int256: check not (x == -2^255 and y == -1)
    if is_signed and typ.bits == 256:
        min_int = 1 << 255
        x_is_min = b.eq(x, IRLiteral(min_int))
        y_is_neg1 = b.iszero(b.not_(y))
        special_case = b.and_(x_is_min, y_is_neg1)
        ok = b.iszero(special_case)
        with b.error_context("safediv"):
            b.assert_(ok)
    elif is_signed and typ.bits < 256:
        # For smaller signed types, clamp result
        res = clamp_basetype(b, res, typ)

    return res


def safe_mod(
    b: VenomBuilder, x: IROperand, y: IROperand, typ: Union[IntegerT, DecimalT]
) -> IROperand:
    """Modulo with divisor check."""
    if not isinstance(typ, (IntegerT, DecimalT)):
        raise CompilerPanic("% operator only valid for integers and decimals")

    is_signed = typ.is_signed

    with b.error_context("safemod"):
        # Clamp divisor > 0
        if is_signed:
            y_gt_zero = b.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = b.gt(y, IRLiteral(0))
        b.assert_(y_gt_zero)

        MOD = b.smod if is_signed else b.mod
        return MOD(x, y)


def safe_pow(
    b: VenomBuilder,
    x: IROperand,
    y: IROperand,
    typ: IntegerT,
    base_literal: Optional[int] = None,
    exp_literal: Optional[int] = None,
) -> IROperand:
    """Exponentiation with bounds checking.

    Requires at least one operand to be a literal for bounds computation.
    Pass base_literal or exp_literal if known at compile time.
    """
    if not isinstance(typ, IntegerT):
        raise TypeCheckFailure("pow only valid for integers")

    is_signed = typ.is_signed
    bits = typ.bits

    ok: IROperand
    if base_literal is not None:
        # Base is literal - compute max exponent at compile time
        base_val = base_literal
        if base_val in (-1, 0, 1):
            # For special bases, just need y >= 0 for signed
            if is_signed:
                # sge(y, 0) = iszero(slt(y, 0))
                ok = b.iszero(b.slt(y, IRLiteral(0)))
            else:
                ok = IRLiteral(1)  # always ok for unsigned
        else:
            upper_bound = calculate_largest_power(base_val, bits, is_signed)
            ok = b.iszero(b.gt(y, IRLiteral(upper_bound)))
        with b.error_context("safepow"):
            b.assert_(ok)

    elif exp_literal is not None:
        # Exponent is literal - compute max base at compile time
        exp_val = exp_literal
        if exp_val in (0, 1):
            ok = IRLiteral(1)  # always ok
        else:
            lower_bound, upper_bound = calculate_largest_base(exp_val, bits, is_signed)
            if is_signed:
                # sge(x, lower_bound) = iszero(slt(x, lower_bound))
                ge_lower = b.iszero(b.slt(x, IRLiteral(lower_bound)))
                le_upper = b.iszero(b.sgt(x, IRLiteral(upper_bound)))
                ok = b.and_(ge_lower, le_upper)
            else:
                ok = b.iszero(b.gt(x, IRLiteral(upper_bound)))
        with b.error_context("safepow"):
            b.assert_(ok)

    else:
        # Neither operand is literal - not currently supported
        raise TypeCheckFailure("pow requires at least one literal operand")

    return b.exp(x, y)


def clamp_basetype(b: VenomBuilder, val: IROperand, typ: Union[IntegerT, DecimalT]) -> IROperand:
    """Clamp value to type bounds."""
    lo, hi = typ.int_bounds

    if typ.is_signed:
        # signed: lo <= val <= hi
        # sge(val, lo) = iszero(slt(val, lo))
        ge_lo = b.iszero(b.slt(val, IRLiteral(lo)))
        le_hi = b.iszero(b.sgt(val, IRLiteral(hi)))
        ok = b.and_(ge_lo, le_hi)
    else:
        # unsigned: 0 <= val <= hi (val is always >= 0 in unsigned)
        ok = b.iszero(b.gt(val, IRLiteral(hi)))

    b.assert_(ok)
    return val

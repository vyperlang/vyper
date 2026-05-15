from __future__ import annotations

from vyper.utils import wrap256

from .value_range import RANGE_WIDTH_LIMIT, SIGNED_MAX, SIGNED_MIN, UNSIGNED_MAX, ValueRange


def _range_spans_sign_boundary(r: ValueRange) -> bool:
    """
    Check if a range spans the signed/unsigned boundary.

    A range spans the boundary if it contains both negative values
    (which are large unsigned values >= 2^255) and non-negative values.
    This is important because unsigned EVM operations like lt/gt treat
    negative signed values as very large positive values.
    """
    if r.is_top or r.is_empty:
        return r.is_top  # TOP spans everything, BOTTOM spans nothing
    return r.lo < 0 and r.hi >= 0


def eval_add(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate add instruction."""
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()
    if lhs.is_constant and rhs.is_constant:
        result = lhs.lo + rhs.lo
        if result < SIGNED_MIN or result > UNSIGNED_MAX:
            result = wrap256(result)
        return ValueRange.constant(result)
    # TODO: could be more precise for negative operands when ranges don't wrap
    if lhs.lo < 0 or rhs.lo < 0:
        return ValueRange.top()
    if (lhs.hi - lhs.lo) > RANGE_WIDTH_LIMIT or (rhs.hi - rhs.lo) > RANGE_WIDTH_LIMIT:
        return ValueRange.top()

    lo = lhs.lo + rhs.lo
    hi = lhs.hi + rhs.hi
    if hi > UNSIGNED_MAX:
        return ValueRange.top()
    return ValueRange.iv(lo, hi)


def eval_sub(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate sub instruction."""
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()
    if lhs.is_constant and rhs.is_constant:
        result = lhs.lo - rhs.lo
        if result < SIGNED_MIN or result > UNSIGNED_MAX:
            result = wrap256(result)
        return ValueRange.constant(result)
    if (lhs.hi - lhs.lo) > RANGE_WIDTH_LIMIT or (rhs.hi - rhs.lo) > RANGE_WIDTH_LIMIT:
        return ValueRange.top()

    lo = lhs.lo - rhs.hi
    hi = lhs.hi - rhs.lo
    if lo < SIGNED_MIN or hi > UNSIGNED_MAX or lo > hi:
        return ValueRange.top()
    return ValueRange.iv(lo, hi)


def eval_mul(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate mul instruction."""
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    # Handle constant zero case: 0 * anything = 0
    if lhs.is_constant and lhs.lo == 0:
        return ValueRange.constant(0)
    if rhs.is_constant and rhs.lo == 0:
        return ValueRange.constant(0)

    if lhs.is_constant and rhs.is_constant:
        result = lhs.lo * rhs.lo
        if result < SIGNED_MIN or result > UNSIGNED_MAX:
            result = wrap256(result)
        return ValueRange.constant(result)
    # For non-constant ranges, only handle non-negative values
    if lhs.lo < 0 or rhs.lo < 0:
        return ValueRange.top()
    if (lhs.hi - lhs.lo) > RANGE_WIDTH_LIMIT or (rhs.hi - rhs.lo) > RANGE_WIDTH_LIMIT:
        return ValueRange.top()

    # Check for potential overflow before computing
    if lhs.hi > 0 and rhs.hi > UNSIGNED_MAX // lhs.hi:
        return ValueRange.top()

    lo = lhs.lo * rhs.lo
    hi = lhs.hi * rhs.hi
    if hi > UNSIGNED_MAX:
        return ValueRange.top()
    return ValueRange.iv(lo, hi)


def eval_and(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate bitwise and instruction.

    For `and x, mask` where mask is a literal:
    - Result is always in [0, mask] (for positive mask)
    - If x can be negative (large unsigned), the low bits could be anything

    Example: `and x, 255` where x ∈ [-128, 127]:
    - x = 127: result = 127
    - x = -128 (= 0xFF...FF80): result = 0x80 = 128
    - x = -1 (= 0xFF...FF): result = 0xFF = 255

    So the result should be [0, 255], not [0, 127].

    Special case: AND with -1 (all bits set) is identity, so return
    the input range unchanged.
    """
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    mask = None
    other = None

    if lhs.is_constant:
        mask = lhs.as_constant()
        other = rhs
    elif rhs.is_constant:
        mask = rhs.as_constant()
        other = lhs

    if mask is None or other is None:
        return ValueRange.top()

    mask = wrap256(mask)

    # AND with -1 (all bits set) is identity
    if mask == UNSIGNED_MAX:
        return other

    # If the range includes negative values, those are large unsigned values
    # with potentially all bits set in the low positions. The AND result
    # could be any value from 0 to the mask.
    if other.lo < 0:
        # Range includes negative values, result could be [0, mask]
        return ValueRange.iv(0, mask)

    # For non-negative ranges, the result is bounded by both the range
    # maximum and the mask
    hi = min(other.hi, mask)
    return ValueRange.iv(0, hi)


def eval_byte(index: ValueRange, value: ValueRange) -> ValueRange:
    """Evaluate byte instruction.

    EVM byte(N, x) returns the N-th byte (from high end, big-endian).
    When N >= 32, the result is always 0.
    """
    if index.is_empty or value.is_empty:
        return ValueRange.empty()

    idx = index.as_constant()
    if idx is not None:
        idx = wrap256(idx)

    if idx is not None and idx >= 32:
        return ValueRange.constant(0)

    # Use value range to constrain result when possible
    if idx is not None and not value.is_top and value.lo >= 0:
        # byte N extracts bits at position (31-N)*8 to (31-N)*8+7
        shift = (31 - idx) * 8

        # If entire range is below this byte position, result is 0
        if value.hi < (1 << shift):
            return ValueRange.constant(0)

        # Check if range spans multiple "byte boundaries"
        lo_prefix = value.lo >> (shift + 8)
        hi_prefix = value.hi >> (shift + 8)

        if lo_prefix == hi_prefix:
            # Same prefix - byte range is bounded
            lo_byte = (value.lo >> shift) & 0xFF
            hi_byte = (value.hi >> shift) & 0xFF
            return ValueRange.iv(lo_byte, hi_byte)

    return ValueRange.bytes_range()


def eval_signextend(index: ValueRange, value: ValueRange) -> ValueRange:
    """Evaluate signextend instruction.

    SIGNEXTEND(b, x) sign-extends x from (b+1)*8 bits to 256 bits.
    It operates on the LOW BITS of x, ignoring the high bits.

    For example, signextend(0, 384) where 384 = 0x180:
    - Low byte = 0x80 (bit 7 is set)
    - Result = 0xFF...FF80 = -128 (sign-extended)

    The old implementation incorrectly intersected the input range with
    the output range, which would give BOTTOM for inputs like 384.
    """
    if index.is_empty or value.is_empty:
        return ValueRange.empty()

    idx = index.as_constant()
    if idx is not None:
        idx = wrap256(idx)

    if idx is None:
        return ValueRange.top()
    if idx >= 32:
        return value

    bits = 8 * (idx + 1)
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    lo = -(1 << (bits - 1))  # e.g., -128 for index=0
    hi = (1 << (bits - 1)) - 1  # e.g., 127 for index=0

    # For constant inputs, compute the exact result
    if value.is_constant:
        val = value.lo
        # Extract low bits and sign-extend
        low_bits = val & mask
        if low_bits & sign_bit:
            # Sign bit is set, extend with 1s
            result = low_bits - (1 << bits)
        else:
            # Sign bit is clear, result is just the low bits
            result = low_bits
        return ValueRange.constant(result)

    # For ranges, if the range fits within the target signed range,
    # we can intersect. Otherwise, the result could be any value
    # in the signed output range since high bits are ignored.
    if value.lo >= lo and value.hi <= hi:
        # Input already within target range, sign extension is identity
        return value

    # For wide ranges or ranges outside target, the low bits could be
    # anything, so return the full signed range for the given byte width
    return ValueRange.iv(lo, hi)


def eval_mod(dividend: ValueRange, divisor: ValueRange) -> ValueRange:
    """Evaluate mod instruction."""
    if dividend.is_empty or divisor.is_empty:
        return ValueRange.empty()
    d = divisor.as_constant()
    if d is None:
        return ValueRange.top()
    d = wrap256(d)
    if d == 0:
        return ValueRange.constant(0)
    return ValueRange.iv(0, d - 1)


def eval_div(dividend: ValueRange, divisor: ValueRange) -> ValueRange:
    """Evaluate div instruction (unsigned division)."""
    if dividend.is_empty or divisor.is_empty:
        return ValueRange.empty()
    d = divisor.as_constant()
    if d is None:
        return ValueRange.top()
    d = wrap256(d)
    if d == 0:
        return ValueRange.constant(0)
    # TODO: could handle negative dividend ranges by converting to unsigned
    # interpretation, but this requires handling disjoint ranges
    if dividend.lo < 0:
        return ValueRange.top()
    return ValueRange.iv(dividend.lo // d, dividend.hi // d)


def eval_shr(shift: ValueRange, value: ValueRange) -> ValueRange:
    """Evaluate shr (shift right) instruction."""
    if shift.is_empty or value.is_empty:
        return ValueRange.empty()
    s = shift.as_constant()
    if s is None:
        return ValueRange.top()
    s = wrap256(s)
    # shift >= 256 always produces 0 regardless of input
    if s >= 256:
        return ValueRange.constant(0)
    if value.lo < 0:
        return ValueRange.top()
    amount = 1 << s
    return ValueRange.iv(value.lo // amount, value.hi // amount)


def eval_shl(shift: ValueRange, value: ValueRange) -> ValueRange:
    """Evaluate shl (shift left) instruction."""
    if shift.is_empty or value.is_empty:
        return ValueRange.empty()
    s = shift.as_constant()
    if s is None:
        return ValueRange.top()
    s = wrap256(s)
    # shift >= 256 always produces 0 regardless of input
    if s >= 256:
        return ValueRange.constant(0)
    if value.lo < 0:
        return ValueRange.top()
    max_input = UNSIGNED_MAX >> s
    if value.hi > max_input:
        return ValueRange.top()
    result_lo = value.lo << s
    result_hi = value.hi << s
    # Convert to signed representation for consistency with range system
    result_lo = wrap256(result_lo, signed=True)
    result_hi = wrap256(result_hi, signed=True)
    # If conversion causes lo > hi (range wraps around), return TOP
    if result_lo > result_hi:
        return ValueRange.top()
    return ValueRange.iv(result_lo, result_hi)


def eval_sar(shift: ValueRange, value: ValueRange) -> ValueRange:
    """Evaluate sar (arithmetic shift right) instruction."""
    if shift.is_empty or value.is_empty:
        return ValueRange.empty()
    s = shift.as_constant()
    if s is None:
        return ValueRange.top()
    s = wrap256(s)
    if value.hi > SIGNED_MAX:
        return ValueRange.top()
    if s >= 256:
        if value.lo >= 0:
            return ValueRange.constant(0)
        if value.hi < 0:
            return ValueRange.constant(-1)
        return ValueRange.iv(-1, 0)
    return ValueRange.iv(value.lo >> s, value.hi >> s)


def eval_sdiv(dividend: ValueRange, divisor: ValueRange) -> ValueRange:
    """Evaluate sdiv (signed division) instruction.

    EVM sdiv interprets both operands as signed and returns a signed result.
    Special case: SIGNED_MIN / -1 = SIGNED_MIN (overflow, doesn't negate).
    """
    if dividend.is_empty or divisor.is_empty:
        return ValueRange.empty()
    d = divisor.as_constant()
    # d is already signed from as_constant()
    if d is None:
        return ValueRange.top()
    if d == 0:
        return ValueRange.constant(0)

    # For constant dividend, compute exact result
    if dividend.is_constant:
        dv = dividend.lo
        # Special case: SIGNED_MIN / -1 = SIGNED_MIN (no negation due to overflow)
        if dv == SIGNED_MIN and d == -1:
            return ValueRange.constant(SIGNED_MIN)
        # Standard signed division
        sign = -1 if (dv < 0) != (d < 0) else 1
        result = sign * (abs(dv) // abs(d))
        return ValueRange.constant(result)

    # For ranges, compute bounds
    # Division by positive divisor preserves order: lo/d <= x/d <= hi/d
    # Division by negative divisor reverses order: hi/d <= x/d <= lo/d
    if d > 0:
        # Truncation toward zero means we need to be careful with bounds
        # Python uses floor division, so for negative dividends we adjust
        if dividend.lo >= 0:
            result_lo = dividend.lo // d
            result_hi = dividend.hi // d
        elif dividend.hi < 0:
            # Both negative: division truncates toward zero
            # -7 // 3 in EVM = -2 (truncate), in Python = -3 (floor)
            result_hi = -(abs(dividend.lo) // d)
            result_lo = -(abs(dividend.hi) // d)
        else:
            # Range spans zero - result spans from negative to positive
            result_lo = -(abs(dividend.lo) // d)
            result_hi = dividend.hi // d
    else:
        # Negative divisor - more complex, return TOP for now
        # TODO: could be more precise for negative divisors
        return ValueRange.top()

    return ValueRange.iv(result_lo, result_hi)


def eval_smod(dividend: ValueRange, divisor: ValueRange) -> ValueRange:
    """Evaluate smod (signed modulo) instruction.

    EVM smod: the result has the same sign as the dividend.
    smod(x, y) = sign(x) * (abs(x) % abs(y))
    """
    if dividend.is_empty or divisor.is_empty:
        return ValueRange.empty()
    d = divisor.as_constant()
    # d is already signed from as_constant()
    if d is None:
        return ValueRange.top()
    if d == 0:
        return ValueRange.constant(0)
    limit = abs(d) - 1

    # Result sign follows dividend sign, so we can narrow based on dividend range
    if dividend.lo >= 0:
        # Dividend is non-negative, result is non-negative
        return ValueRange.iv(0, min(limit, dividend.hi))
    elif dividend.hi <= 0:
        # Dividend is non-positive, result is non-positive
        return ValueRange.iv(max(-limit, dividend.lo), 0)
    else:
        # Dividend spans zero, result could be in full range
        return ValueRange.iv(-limit, limit)


def eval_compare(opcode: str, lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate comparison instructions (lt, gt, slt, sgt).

    IMPORTANT: EVM lt/gt are UNSIGNED comparisons, while slt/sgt are SIGNED.
    In unsigned interpretation, negative signed values (e.g., -1 = 0xFF...FF)
    are very large positive values. This means:
    - lt(-1, 1) = 0 (because MAX_UINT > 1 in unsigned)
    - slt(-1, 1) = 1 (because -1 < 1 in signed)

    When a range spans the signed/unsigned boundary (contains both negative
    and non-negative values), unsigned comparisons cannot be resolved
    definitively using signed range bounds.
    """
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    is_signed = opcode in {"slt", "sgt"}

    # For unsigned comparisons, if either range spans the sign boundary,
    # we cannot make definitive conclusions because negative values in
    # signed representation are large positive values in unsigned.
    if not is_signed:
        if _range_spans_sign_boundary(lhs) or _range_spans_sign_boundary(rhs):
            return ValueRange.bool_range()

        # For unsigned comparisons with non-negative ranges, or purely
        # negative ranges (both operands same sign), we can compare directly.
        # But if one is negative and one is positive, the negative one is larger.
        if lhs.hi < 0 and rhs.lo >= 0:
            # lhs is all negative (large unsigned), rhs is all non-negative
            # In unsigned: lhs > rhs always
            if rhs.hi <= SIGNED_MAX:
                if opcode == "lt":
                    return ValueRange.constant(0)
                else:  # gt
                    return ValueRange.constant(1)
            return ValueRange.bool_range()
        if lhs.lo >= 0 and rhs.hi < 0:
            # lhs is all non-negative, rhs is all negative (large unsigned)
            # In unsigned: lhs < rhs always
            if lhs.hi <= SIGNED_MAX:
                if opcode == "lt":
                    return ValueRange.constant(1)
                else:  # gt
                    return ValueRange.constant(0)
            return ValueRange.bool_range()

    # Now we can use signed comparison logic (works for both signed ops
    # and unsigned ops where both ranges have the same sign)
    if opcode in {"lt", "slt"}:
        if lhs.hi < rhs.lo:
            return ValueRange.constant(1)
        if lhs.lo >= rhs.hi:
            return ValueRange.constant(0)
    else:
        assert opcode in {"gt", "sgt"}
        if lhs.lo > rhs.hi:
            return ValueRange.constant(1)
        if lhs.hi <= rhs.lo:
            return ValueRange.constant(0)
    return ValueRange.bool_range()


def eval_eq(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate eq (equality) instruction.

    IMPORTANT: In EVM, eq compares 256-bit values directly. -1 and MAX_UINT
    are the same bit pattern (0xFF...FF), so eq(-1, MAX_UINT) = 1.

    We need to normalize values to unsigned representation for comparison
    since the same value can be represented as both -1 (signed) and
    MAX_UINT (unsigned) in our range representation.
    """
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    if lhs.is_constant and rhs.is_constant:
        # Normalize both values to unsigned for comparison
        # wrap256 without signed=True gives unsigned representation
        lhs_val = wrap256(lhs.lo)
        rhs_val = wrap256(rhs.lo)
        return ValueRange.constant(int(lhs_val == rhs_val))

    # For non-constant ranges, check for non-overlap
    # But we need to be careful: ranges that appear disjoint in signed
    # representation might overlap in unsigned (e.g., [-1, -1] and [MAX_UINT, MAX_UINT])
    # This is complex to handle properly, so be conservative
    if _range_spans_sign_boundary(lhs) or _range_spans_sign_boundary(rhs):
        # Ranges span sign boundary, can't easily determine non-overlap
        return ValueRange.bool_range()

    # Both ranges are on the same side of the sign boundary
    # Be conservative if one side is negative and the other includes values
    # with the high bit set, since those overlap in unsigned representation.
    if lhs.hi < 0 and rhs.lo >= 0 and rhs.hi > SIGNED_MAX:
        return ValueRange.bool_range()
    if rhs.hi < 0 and lhs.lo >= 0 and lhs.hi > SIGNED_MAX:
        return ValueRange.bool_range()

    if lhs.hi < rhs.lo or rhs.hi < lhs.lo:
        return ValueRange.constant(0)

    return ValueRange.bool_range()


def eval_iszero(operand: ValueRange) -> ValueRange:
    """Evaluate iszero instruction."""
    if operand.is_empty:
        return ValueRange.empty()
    if operand.is_constant:
        return ValueRange.constant(int(operand.lo == 0))
    if operand.lo > 0 or operand.hi < 0:
        return ValueRange.constant(0)
    return ValueRange.bool_range()


def eval_or(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate bitwise or instruction.

    For `or x, y`:
    - If both are constants: return x | y
    - If either operand is 0: return the other
    - If either operand is -1 (all bits set): return -1
    - Otherwise: return TOP (hard to bound precisely)
    """
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    # Both constants: compute exact result
    if lhs.is_constant and rhs.is_constant:
        # Convert to unsigned for bitwise op, then wrap result
        a = wrap256(lhs.lo)
        b = wrap256(rhs.lo)
        return ValueRange.constant(wrap256(a | b, signed=True))

    # If either is constant 0: return the other
    if lhs.is_constant and lhs.lo == 0:
        return rhs
    if rhs.is_constant and rhs.lo == 0:
        return lhs

    # If either is -1 (all bits set): result is -1
    if lhs.is_constant and wrap256(lhs.lo) == UNSIGNED_MAX:
        return ValueRange.constant(-1)
    if rhs.is_constant and wrap256(rhs.lo) == UNSIGNED_MAX:
        return ValueRange.constant(-1)

    return ValueRange.top()


def eval_xor(lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate bitwise xor instruction.

    For `xor x, y`:
    - If both are constants: return x ^ y
    - Otherwise: return TOP
    """
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    # Both constants: compute exact result
    if lhs.is_constant and rhs.is_constant:
        a = wrap256(lhs.lo)
        b = wrap256(rhs.lo)
        return ValueRange.constant(wrap256(a ^ b, signed=True))

    return ValueRange.top()


def eval_not(operand: ValueRange) -> ValueRange:
    """Evaluate bitwise not instruction.

    EVM NOT: ~x = UNSIGNED_MAX ^ x (flips all bits)

    For constant input: return exact result
    Otherwise: return TOP
    """
    if operand.is_empty:
        return ValueRange.empty()

    if operand.is_constant:
        val = wrap256(operand.lo)
        result = UNSIGNED_MAX ^ val
        return ValueRange.constant(wrap256(result, signed=True))

    return ValueRange.top()


def eval_op(opcode: str, lhs: ValueRange, rhs: ValueRange) -> ValueRange:
    """Evaluate a binary opcode on two ranges.

    Pure case dispatch. For unary ops, caller passes ValueRange.top() as rhs
    (unused by the evaluator).
    """
    if opcode == "add":
        return eval_add(lhs, rhs)
    if opcode == "sub":
        return eval_sub(lhs, rhs)
    if opcode == "mul":
        return eval_mul(lhs, rhs)
    if opcode == "and":
        return eval_and(lhs, rhs)
    if opcode == "or":
        return eval_or(lhs, rhs)
    if opcode == "xor":
        return eval_xor(lhs, rhs)
    if opcode == "byte":
        return eval_byte(lhs, rhs)
    if opcode == "signextend":
        return eval_signextend(lhs, rhs)
    if opcode == "mod":
        return eval_mod(lhs, rhs)
    if opcode == "div":
        return eval_div(lhs, rhs)
    if opcode == "sdiv":
        return eval_sdiv(lhs, rhs)
    if opcode == "smod":
        return eval_smod(lhs, rhs)
    if opcode == "shr":
        return eval_shr(lhs, rhs)
    if opcode == "shl":
        return eval_shl(lhs, rhs)
    if opcode == "sar":
        return eval_sar(lhs, rhs)
    if opcode == "eq":
        return eval_eq(lhs, rhs)
    if opcode in ("lt", "gt", "slt", "sgt"):
        return eval_compare(opcode, lhs, rhs)
    if opcode == "iszero":
        return eval_iszero(lhs)
    if opcode == "not":
        return eval_not(lhs)
    return ValueRange.top()

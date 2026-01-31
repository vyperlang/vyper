from __future__ import annotations

from typing import Callable, Optional

from vyper.utils import wrap256
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable

from .value_range import (
    RANGE_WIDTH_LIMIT,
    SIGNED_MAX,
    SIGNED_MIN,
    UNSIGNED_MAX,
    RangeState,
    ValueRange,
)


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


# Type alias for range evaluator functions
RangeEvaluator = Callable[[IRInstruction, RangeState], ValueRange]


def _get_uint_literal(op: IROperand) -> Optional[int]:
    """Extract unsigned literal value from operand, if it is a literal."""
    if not isinstance(op, IRLiteral):
        return None
    return wrap256(op.value)


def _get_signed_literal(op: IROperand) -> Optional[int]:
    """Extract signed literal value from operand, if it is a literal."""
    if not isinstance(op, IRLiteral):
        return None
    return wrap256(op.value, signed=True)


def _operand_range(operand: IROperand, env: RangeState) -> ValueRange:
    """Get the range of an operand from the current environment.

    Literals are normalized to signed representation since the range system
    uses signed bounds internally. This ensures values >= 2^255 are treated
    as negative numbers (e.g., 2^255 becomes SIGNED_MIN).
    """
    if isinstance(operand, IRLiteral):
        return ValueRange.constant(wrap256(operand.value, signed=True))
    if isinstance(operand, IRVariable):
        return env.get(operand, ValueRange.top())
    return ValueRange.top()


def _eval_assign(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate assign instruction."""
    op = inst.operands[-1]
    return _operand_range(op, state)


def _eval_add(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate add instruction."""
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)
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
    return ValueRange((lo, hi))


def _eval_sub(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate sub instruction."""
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)
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
    return ValueRange((lo, hi))


def _eval_mul(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate mul instruction."""
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)
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
    return ValueRange((lo, hi))


def _eval_and(inst: IRInstruction, state: RangeState) -> ValueRange:
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
    first = inst.operands[-1]
    second = inst.operands[-2]
    first_range = _operand_range(first, state)
    second_range = _operand_range(second, state)

    if first_range.is_empty or second_range.is_empty:
        return ValueRange.empty()

    literal: Optional[int] = None
    other_range: Optional[ValueRange] = None

    if isinstance(first, IRLiteral):
        literal = wrap256(first.value)
        other_range = second_range
    elif isinstance(second, IRLiteral):
        literal = wrap256(second.value)
        other_range = first_range

    if literal is None or other_range is None:
        return ValueRange.top()

    # AND with -1 (all bits set) is identity
    if literal == UNSIGNED_MAX:
        return other_range

    # If the range includes negative values, those are large unsigned values
    # with potentially all bits set in the low positions. The AND result
    # could be any value from 0 to the mask.
    if other_range.lo < 0:
        # Range includes negative values, result could be [0, mask]
        return ValueRange((0, literal))

    # For non-negative ranges, the result is bounded by both the range
    # maximum and the mask
    hi = min(other_range.hi, literal)
    return ValueRange((0, hi))


def _eval_byte(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate byte instruction.

    EVM byte(N, x) returns the N-th byte (from high end, big-endian).
    When N >= 32, the result is always 0.
    """
    index_op = inst.operands[-1]
    value_op = inst.operands[-2]
    value_range = _operand_range(value_op, state)
    if value_range.is_empty:
        return ValueRange.empty()
    index = _get_uint_literal(index_op)
    if index is not None and index >= 32:
        return ValueRange.constant(0)

    # Use value_range to constrain result when possible
    if index is not None and not value_range.is_top and value_range.lo >= 0:
        # byte N extracts bits at position (31-N)*8 to (31-N)*8+7
        shift = (31 - index) * 8

        # If entire range is below this byte position, result is 0
        if value_range.hi < (1 << shift):
            return ValueRange.constant(0)

        # Check if range spans multiple "byte boundaries"
        lo_prefix = value_range.lo >> (shift + 8)
        hi_prefix = value_range.hi >> (shift + 8)

        if lo_prefix == hi_prefix:
            # Same prefix - byte range is bounded
            lo_byte = (value_range.lo >> shift) & 0xFF
            hi_byte = (value_range.hi >> shift) & 0xFF
            return ValueRange((lo_byte, hi_byte))

    return ValueRange.bytes_range()


def _eval_signextend(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate signextend instruction.

    SIGNEXTEND(b, x) sign-extends x from (b+1)*8 bits to 256 bits.
    It operates on the LOW BITS of x, ignoring the high bits.

    For example, signextend(0, 384) where 384 = 0x180:
    - Low byte = 0x80 (bit 7 is set)
    - Result = 0xFF...FF80 = -128 (sign-extended)

    The old implementation incorrectly intersected the input range with
    the output range, which would give BOTTOM for inputs like 384.
    """
    index_op = inst.operands[-1]
    value_op = inst.operands[-2]
    value_range = _operand_range(value_op, state)
    if value_range.is_empty:
        return ValueRange.empty()
    index = _get_uint_literal(index_op)
    if index is None:
        return ValueRange.top()
    if index >= 32:
        return value_range

    bits = 8 * (index + 1)
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    lo = -(1 << (bits - 1))  # e.g., -128 for index=0
    hi = (1 << (bits - 1)) - 1  # e.g., 127 for index=0

    # For constant inputs, compute the exact result
    if value_range.is_constant:
        val = value_range.lo
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
    if value_range.lo >= lo and value_range.hi <= hi:
        # Input already within target range, sign extension is identity
        return value_range

    # For wide ranges or ranges outside target, the low bits could be
    # anything, so return the full signed range for the given byte width
    return ValueRange((lo, hi))


def _eval_mod(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate mod instruction."""
    dividend_op = inst.operands[-1]
    divisor_op = inst.operands[-2]
    dividend_range = _operand_range(dividend_op, state)
    if dividend_range.is_empty:
        return ValueRange.empty()
    divisor = _get_uint_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)
    return ValueRange((0, divisor - 1))


def _eval_div(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate div instruction (unsigned division)."""
    dividend_op = inst.operands[-1]
    divisor_op = inst.operands[-2]
    dividend_range = _operand_range(dividend_op, state)
    if dividend_range.is_empty:
        return ValueRange.empty()
    divisor = _get_uint_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)
    # TODO: could handle negative dividend ranges by converting to unsigned
    # interpretation, but this requires handling disjoint ranges
    if dividend_range.lo < 0:
        return ValueRange.top()
    return ValueRange((dividend_range.lo // divisor, dividend_range.hi // divisor))


def _eval_shr(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate shr (shift right) instruction."""
    shift_op = inst.operands[-1]
    value_op = inst.operands[-2]
    value_range = _operand_range(value_op, state)
    if value_range.is_empty:
        return ValueRange.empty()
    shift = _get_uint_literal(shift_op)
    if shift is None:
        return ValueRange.top()
    # shift >= 256 always produces 0 regardless of input
    if shift >= 256:
        return ValueRange.constant(0)
    if value_range.lo < 0:
        return ValueRange.top()
    amount = 1 << shift
    return ValueRange((value_range.lo // amount, value_range.hi // amount))


def _eval_shl(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate shl (shift left) instruction."""
    shift_op = inst.operands[-1]
    value_op = inst.operands[-2]
    value_range = _operand_range(value_op, state)
    if value_range.is_empty:
        return ValueRange.empty()
    shift = _get_uint_literal(shift_op)
    if shift is None:
        return ValueRange.top()
    # shift >= 256 always produces 0 regardless of input
    if shift >= 256:
        return ValueRange.constant(0)
    if value_range.lo < 0:
        return ValueRange.top()
    max_input = UNSIGNED_MAX >> shift
    if value_range.hi > max_input:
        return ValueRange.top()
    result_lo = value_range.lo << shift
    result_hi = value_range.hi << shift
    # Convert to signed representation for consistency with range system
    result_lo = wrap256(result_lo, signed=True)
    result_hi = wrap256(result_hi, signed=True)
    # If conversion causes lo > hi (range wraps around), return TOP
    if result_lo > result_hi:
        return ValueRange.top()
    return ValueRange((result_lo, result_hi))


def _eval_sar(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate sar (arithmetic shift right) instruction."""
    shift_op = inst.operands[-1]
    value_op = inst.operands[-2]
    shift = _get_uint_literal(shift_op)
    value_range = _operand_range(value_op, state)
    if shift is None:
        return ValueRange.top()
    if value_range.is_empty:
        return ValueRange.empty()
    if value_range.hi > SIGNED_MAX:
        return ValueRange.top()
    if shift >= 256:
        if value_range.lo >= 0:
            return ValueRange.constant(0)
        if value_range.hi < 0:
            return ValueRange.constant(-1)
        return ValueRange((-1, 0))
    return ValueRange((value_range.lo >> shift, value_range.hi >> shift))


def _eval_sdiv(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate sdiv (signed division) instruction.

    EVM sdiv interprets both operands as signed and returns a signed result.
    Special case: SIGNED_MIN / -1 = SIGNED_MIN (overflow, doesn't negate).
    """
    dividend_op = inst.operands[-1]
    divisor_op = inst.operands[-2]
    dividend_range = _operand_range(dividend_op, state)
    if dividend_range.is_empty:
        return ValueRange.empty()
    divisor = _get_signed_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)

    # For constant dividend, compute exact result
    if dividend_range.is_constant:
        dividend = dividend_range.lo
        # Special case: SIGNED_MIN / -1 = SIGNED_MIN (no negation due to overflow)
        if dividend == SIGNED_MIN and divisor == -1:
            return ValueRange.constant(SIGNED_MIN)
        # Standard signed division
        sign = -1 if (dividend < 0) != (divisor < 0) else 1
        result = sign * (abs(dividend) // abs(divisor))
        return ValueRange.constant(result)

    # For ranges, compute bounds
    # Division by positive divisor preserves order: lo/d <= x/d <= hi/d
    # Division by negative divisor reverses order: hi/d <= x/d <= lo/d
    if divisor > 0:
        # Truncation toward zero means we need to be careful with bounds
        # Python uses floor division, so for negative dividends we adjust
        if dividend_range.lo >= 0:
            result_lo = dividend_range.lo // divisor
            result_hi = dividend_range.hi // divisor
        elif dividend_range.hi < 0:
            # Both negative: division truncates toward zero
            # -7 // 3 in EVM = -2 (truncate), in Python = -3 (floor)
            result_hi = -(abs(dividend_range.lo) // divisor)
            result_lo = -(abs(dividend_range.hi) // divisor)
        else:
            # Range spans zero - result spans from negative to positive
            result_lo = -(abs(dividend_range.lo) // divisor)
            result_hi = dividend_range.hi // divisor
    else:
        # Negative divisor - more complex, return TOP for now
        # TODO: could be more precise for negative divisors
        return ValueRange.top()

    return ValueRange((result_lo, result_hi))


def _eval_smod(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate smod (signed modulo) instruction.

    EVM smod: the result has the same sign as the dividend.
    smod(x, y) = sign(x) * (abs(x) % abs(y))
    """
    dividend_op = inst.operands[-1]
    divisor_op = inst.operands[-2]
    dividend_range = _operand_range(dividend_op, state)
    if dividend_range.is_empty:
        return ValueRange.empty()
    divisor = _get_signed_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)
    limit = abs(divisor) - 1

    # Result sign follows dividend sign, so we can narrow based on dividend range
    if dividend_range.lo >= 0:
        # Dividend is non-negative, result is non-negative
        return ValueRange((0, min(limit, dividend_range.hi)))
    elif dividend_range.hi <= 0:
        # Dividend is non-positive, result is non-positive
        return ValueRange((max(-limit, dividend_range.lo), 0))
    else:
        # Dividend spans zero, result could be in full range
        return ValueRange((-limit, limit))


def _eval_compare(inst: IRInstruction, state: RangeState) -> ValueRange:
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
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    opcode = inst.opcode
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


def _eval_eq(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate eq (equality) instruction.

    IMPORTANT: In EVM, eq compares 256-bit values directly. -1 and MAX_UINT
    are the same bit pattern (0xFF...FF), so eq(-1, MAX_UINT) = 1.

    We need to normalize values to unsigned representation for comparison
    since the same value can be represented as both -1 (signed) and
    MAX_UINT (unsigned) in our range representation.
    """
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)

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


def _eval_iszero(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate iszero instruction."""
    operand = inst.operands[-1]
    target = _operand_range(operand, state)
    if target.is_empty:
        return ValueRange.empty()
    if target.is_constant:
        return ValueRange.constant(int(target.lo == 0))
    if target.lo > 0 or target.hi < 0:
        return ValueRange.constant(0)
    return ValueRange.bool_range()


def _eval_or(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate bitwise or instruction.

    For `or x, y`:
    - If both are constants: return x | y
    - If either operand is 0: return the other
    - If either operand is -1 (all bits set): return -1
    - Otherwise: return TOP (hard to bound precisely)
    """
    first = inst.operands[-1]
    second = inst.operands[-2]
    first_range = _operand_range(first, state)
    second_range = _operand_range(second, state)

    if first_range.is_empty or second_range.is_empty:
        return ValueRange.empty()

    # Both constants: compute exact result
    if first_range.is_constant and second_range.is_constant:
        # Convert to unsigned for bitwise op, then wrap result
        a = wrap256(first_range.lo)
        b = wrap256(second_range.lo)
        return ValueRange.constant(wrap256(a | b, signed=True))

    # If either is constant 0: return the other
    if first_range.is_constant and first_range.lo == 0:
        return second_range
    if second_range.is_constant and second_range.lo == 0:
        return first_range

    # If either is -1 (all bits set): result is -1
    if first_range.is_constant and wrap256(first_range.lo) == UNSIGNED_MAX:
        return ValueRange.constant(-1)
    if second_range.is_constant and wrap256(second_range.lo) == UNSIGNED_MAX:
        return ValueRange.constant(-1)

    return ValueRange.top()


def _eval_xor(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate bitwise xor instruction.

    For `xor x, y`:
    - If x and y are the same variable: return 0
    - If both are constants: return x ^ y
    - Otherwise: return TOP
    """
    first = inst.operands[-1]
    second = inst.operands[-2]
    first_range = _operand_range(first, state)
    second_range = _operand_range(second, state)

    if first_range.is_empty or second_range.is_empty:
        return ValueRange.empty()

    # Self-xor optimization: xor %x, %x = 0
    # Must check after empty check to return BOTTOM for unreachable code
    if isinstance(first, IRVariable) and isinstance(second, IRVariable):
        if first == second:
            return ValueRange.constant(0)

    # Both constants: compute exact result
    if first_range.is_constant and second_range.is_constant:
        a = wrap256(first_range.lo)
        b = wrap256(second_range.lo)
        return ValueRange.constant(wrap256(a ^ b, signed=True))

    return ValueRange.top()


def _eval_not(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate bitwise not instruction.

    EVM NOT: ~x = UNSIGNED_MAX ^ x (flips all bits)

    For constant input: return exact result
    Otherwise: return TOP
    """
    operand = inst.operands[-1]
    operand_range = _operand_range(operand, state)

    if operand_range.is_empty:
        return ValueRange.empty()

    if operand_range.is_constant:
        val = wrap256(operand_range.lo)
        result = UNSIGNED_MAX ^ val
        return ValueRange.constant(wrap256(result, signed=True))

    return ValueRange.top()


# Dispatch table mapping opcodes to their evaluator functions
EVAL_DISPATCH: dict[str, RangeEvaluator] = {
    "assign": _eval_assign,
    "add": _eval_add,
    "sub": _eval_sub,
    "mul": _eval_mul,
    "and": _eval_and,
    "or": _eval_or,
    "xor": _eval_xor,
    "not": _eval_not,
    "byte": _eval_byte,
    "signextend": _eval_signextend,
    "mod": _eval_mod,
    "div": _eval_div,
    "sdiv": _eval_sdiv,
    "shr": _eval_shr,
    "shl": _eval_shl,
    "sar": _eval_sar,
    "smod": _eval_smod,
    "lt": _eval_compare,
    "gt": _eval_compare,
    "slt": _eval_compare,
    "sgt": _eval_compare,
    "eq": _eval_eq,
    "iszero": _eval_iszero,
}

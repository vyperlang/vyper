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
    """Get the range of an operand from the current environment."""
    if isinstance(operand, IRLiteral):
        return ValueRange.constant(operand.value)
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
    """Evaluate bitwise and instruction."""
    first = inst.operands[-1]
    second = inst.operands[-2]
    first_range = _operand_range(first, state)
    second_range = _operand_range(second, state)
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

    hi = min(other_range.hi, literal)
    return ValueRange((0, hi))


def _eval_byte(_inst: IRInstruction, _state: RangeState) -> ValueRange:
    """Evaluate byte instruction."""
    return ValueRange.bytes_range()


def _eval_signextend(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate signextend instruction."""
    index_op = inst.operands[-1]
    value_op = inst.operands[-2]
    value_range = _operand_range(value_op, state)
    index = _get_uint_literal(index_op)
    if index is None:
        return value_range
    if index >= 32:
        return value_range

    bits = 8 * (index + 1)
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    target = ValueRange((lo, hi))
    return value_range.intersect(target)


def _eval_mod(inst: IRInstruction, _state: RangeState) -> ValueRange:
    """Evaluate mod instruction."""
    divisor_op = inst.operands[-2]
    divisor = _get_uint_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)
    return ValueRange((0, divisor - 1))


def _eval_div(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate div instruction."""
    dividend_op = inst.operands[-1]
    divisor_op = inst.operands[-2]
    divisor = _get_uint_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)
    dividend_range = _operand_range(dividend_op, state)
    if dividend_range.is_empty or dividend_range.lo < 0:
        return ValueRange.top()
    return ValueRange((dividend_range.lo // divisor, dividend_range.hi // divisor))


def _eval_shr(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate shr (shift right) instruction."""
    shift_op = inst.operands[-1]
    value_op = inst.operands[-2]
    shift = _get_uint_literal(shift_op)
    value_range = _operand_range(value_op, state)
    if shift is None:
        return ValueRange.top()
    if value_range.is_empty or value_range.lo < 0:
        return ValueRange.top()
    if shift >= 256:
        return ValueRange.constant(0)
    amount = 1 << shift
    return ValueRange((value_range.lo // amount, value_range.hi // amount))


def _eval_shl(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate shl (shift left) instruction."""
    shift_op = inst.operands[-1]
    value_op = inst.operands[-2]
    shift = _get_uint_literal(shift_op)
    value_range = _operand_range(value_op, state)
    if shift is None:
        return ValueRange.top()
    if value_range.is_empty or value_range.lo < 0:
        return ValueRange.top()
    if shift >= 256:
        return ValueRange.constant(0)
    max_input = UNSIGNED_MAX >> shift
    if value_range.hi > max_input:
        return ValueRange.top()
    return ValueRange((value_range.lo << shift, value_range.hi << shift))


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


def _eval_smod(inst: IRInstruction, _state: RangeState) -> ValueRange:
    """Evaluate smod (signed modulo) instruction."""
    divisor_op = inst.operands[-2]
    divisor = _get_signed_literal(divisor_op)
    if divisor is None:
        return ValueRange.top()
    if divisor == 0:
        return ValueRange.constant(0)
    limit = abs(divisor) - 1
    return ValueRange((-limit, limit))


def _eval_compare(inst: IRInstruction, state: RangeState) -> ValueRange:
    """Evaluate comparison instructions (lt, gt, slt, sgt)."""
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)
    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    opcode = inst.opcode
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
    """Evaluate eq (equality) instruction."""
    lhs = _operand_range(inst.operands[-1], state)
    rhs = _operand_range(inst.operands[-2], state)

    if lhs.is_empty or rhs.is_empty:
        return ValueRange.empty()

    if lhs.is_constant and rhs.is_constant:
        return ValueRange.constant(int(lhs.lo == rhs.lo))

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


# Dispatch table mapping opcodes to their evaluator functions
EVAL_DISPATCH: dict[str, RangeEvaluator] = {
    "assign": _eval_assign,
    "add": _eval_add,
    "sub": _eval_sub,
    "mul": _eval_mul,
    "and": _eval_and,
    "byte": _eval_byte,
    "signextend": _eval_signextend,
    "mod": _eval_mod,
    "div": _eval_div,
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

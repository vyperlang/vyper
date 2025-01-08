import operator
from typing import Callable, Optional

from vyper.utils import (
    SizeLimits,
    evm_div,
    evm_mod,
    evm_not,
    evm_pow,
    int_bounds,
    signed_to_unsigned,
    unsigned_to_signed,
)
from vyper.venom.basicblock import IRLiteral, IROperand


def lit_eq(op: IROperand, val: int) -> bool:
    return isinstance(op, IRLiteral) and op.value == val


def _unsigned_to_signed(value: int) -> int:
    assert isinstance(value, int)
    return unsigned_to_signed(value, 256)


def _signed_to_unsigned(value: int) -> int:
    assert isinstance(value, int)
    return signed_to_unsigned(value, 256)


def _wrap_signed_binop(operation):
    def wrapper(ops: list[IROperand]) -> IRLiteral:
        assert len(ops) == 2
        first = _unsigned_to_signed(ops[1].value)
        second = _unsigned_to_signed(ops[0].value)
        return IRLiteral(_signed_to_unsigned(operation(first, second)))

    return wrapper


def _wrap_binop(operation):
    def wrapper(ops: list[IROperand]) -> IRLiteral:
        assert len(ops) == 2
        first = _signed_to_unsigned(ops[1].value)
        second = _signed_to_unsigned(ops[0].value)
        ret = operation(first, second)
        return IRLiteral(ret & SizeLimits.MAX_UINT256)

    return wrapper


def _wrap_unop(operation):
    def wrapper(ops: list[IROperand]) -> IRLiteral:
        assert len(ops) == 1
        value = _signed_to_unsigned(ops[0].value)
        ret = operation(value)
        return IRLiteral(ret & SizeLimits.MAX_UINT256)

    return wrapper


def _evm_signextend(nbytes, value) -> int:
    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"

    if nbytes > 31:
        return value

    assert nbytes >= 0

    sign_bit = 1 << (nbytes * 8 + 7)
    if value & sign_bit:
        value |= SizeLimits.CEILING_UINT256 - sign_bit
    else:
        value &= sign_bit - 1

    return value


def _evm_iszero(value: int) -> int:
    assert SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    return int(value == 0)  # 1 if True else 0


def _evm_shr(shift_len: int, value: int) -> int:
    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    assert shift_len >= 0
    return value >> shift_len


def _evm_shl(shift_len: int, value: int) -> int:
    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    if shift_len >= 256:
        return 0
    assert shift_len >= 0
    return (value << shift_len) & SizeLimits.MAX_UINT256


def _evm_sar(shift_len: int, value: int) -> int:
    assert SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_INT256, "Value out of bounds"
    assert shift_len >= 0
    return value >> shift_len


def _comparison_eval(opcode: str, ops: list[IROperand]):
    # x < x always evaluates to False
    if ops[0] == ops[1]:
        return IRLiteral(0)

    signed = "s" in opcode
    lo, hi = int_bounds(bits=256, signed=signed)

    # note: remember order of operands!
    # text of (gt, [x, y]) is: `y > x`
    a, b = ops[1], ops[0]
    if "gt" in opcode:
        # x > hi => False
        # lo > x => False
        if lit_eq(a, lo) or lit_eq(b, hi):
            return IRLiteral(0)
    else:
        # hi < x => False
        # x < lo => False
        if lit_eq(a, hi) or lit_eq(b, lo):
            return IRLiteral(0)

    return None


ARITHMETIC_OPS: dict[str, Callable[[list[IRLiteral]], IRLiteral]] = {
    "add": _wrap_binop(operator.add),
    "sub": _wrap_binop(operator.sub),
    "mul": _wrap_binop(operator.mul),
    "div": _wrap_binop(evm_div),
    "sdiv": _wrap_signed_binop(evm_div),
    "mod": _wrap_binop(evm_mod),
    "smod": _wrap_signed_binop(evm_mod),
    "exp": _wrap_binop(evm_pow),
    "eq": _wrap_binop(operator.eq),
    "lt": _wrap_binop(operator.lt),
    "gt": _wrap_binop(operator.gt),
    "slt": _wrap_signed_binop(operator.lt),
    "sgt": _wrap_signed_binop(operator.gt),
    "or": _wrap_binop(operator.or_),
    "and": _wrap_binop(operator.and_),
    "xor": _wrap_binop(operator.xor),
    "not": _wrap_unop(evm_not),
    "signextend": _wrap_binop(_evm_signextend),
    "iszero": _wrap_unop(_evm_iszero),
    "shr": _wrap_binop(_evm_shr),
    "shl": _wrap_binop(_evm_shl),
    "sar": _wrap_signed_binop(_evm_sar),
    "store": _wrap_unop(lambda ops: ops[0].value),
}


def eval_arith(opcode: str, ops: list[IROperand]) -> IRLiteral | None:
    if all(isinstance(op, IRLiteral) for op in ops):
        fn = ARITHMETIC_OPS[opcode]
        return fn(ops)  # type: ignore

    # try algebraic transformations
    return _algebraic_eval(opcode, ops)


def _algebraic_eval(opcode: str, ops: list[IROperand]) -> Optional[IRLiteral]:
    if opcode in ("mul", "smul", "and"):
        if any(lit_eq(op, 0) for op in ops):
            return IRLiteral(0)

    if opcode in ("div", "sdiv", "mod", "smod") and lit_eq(ops[0], 0):
        return IRLiteral(0)

    if opcode in ("mod", "smod") and lit_eq(ops[0], 1):
        return IRLiteral(0)

    # x - x == x ^ x == 0
    if opcode in ("xor", "sub") and ops[0] == ops[1]:
        return IRLiteral(0)

    # variable equality: x == x => 1
    if opcode == "eq" and ops[0] == ops[1]:
        return IRLiteral(1)

    # x | 0xff..ff == 0xff..ff
    if opcode == "or" and any(lit_eq(op, SizeLimits.MAX_UINT256) for op in ops):
        return IRLiteral(SizeLimits.MAX_UINT256)

    if opcode == "exp":
        if lit_eq(ops[0], 0):
            return IRLiteral(1)

        if lit_eq(ops[1], 1):
            return IRLiteral(1)

    if opcode in ("lt", "gt", "slt", "sgt"):
        return _comparison_eval(opcode, ops)

    return None

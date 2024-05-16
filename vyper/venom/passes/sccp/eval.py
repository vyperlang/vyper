import operator
from typing import Callable

from vyper.utils import (
    SizeLimits,
    evm_div,
    evm_mod,
    evm_pow,
    signed_to_unsigned,
    unsigned_to_signed,
)
from vyper.venom.basicblock import IROperand


def _unsigned_to_signed(value: int) -> int:
    if value <= SizeLimits.MAX_INT256:
        return value  # fast exit
    else:
        return unsigned_to_signed(value, 256)


def _signed_to_unsigned(value: int) -> int:
    if value >= 0:
        return value  # fast exit
    else:
        return signed_to_unsigned(value, 256)


def _wrap_signed_binop(operation):
    def wrapper(ops: list[IROperand]) -> int:
        first = _unsigned_to_signed(ops[1].value)
        second = _unsigned_to_signed(ops[0].value)
        return _signed_to_unsigned(int(operation(first, second)))

    return wrapper


def _wrap_binop(operation):
    def wrapper(ops: list[IROperand]) -> int:
        first = _signed_to_unsigned(ops[1].value)
        second = _signed_to_unsigned(ops[0].value)
        ret = operation(first, second)
        assert isinstance(ret, int)
        return ret & SizeLimits.MAX_UINT256

    return wrapper


def _evm_signextend(ops: list[IROperand]) -> int:
    value = ops[0].value
    nbytes = ops[1].value

    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"

    if nbytes > 31:
        return value

    sign_bit = 1 << (nbytes * 8 + 7)
    if value & sign_bit:
        value |= SizeLimits.CEILING_UINT256 - sign_bit
    else:
        value &= sign_bit - 1

    return value


def _evm_iszero(ops: list[IROperand]) -> int:
    value = ops[0].value
    assert SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    return int(value == 0)  # 1 if True else 0


def _evm_shr(ops: list[IROperand]) -> int:
    value = ops[0].value
    shift_len = ops[1].value
    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    return value >> shift_len


def _evm_shl(ops: list[IROperand]) -> int:
    value = ops[0].value
    shift_len = ops[1].value
    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    if shift_len >= 256:
        return 0
    return (value << shift_len) & SizeLimits.MAX_UINT256


def _evm_sar(ops: list[IROperand]) -> int:
    value = _unsigned_to_signed(ops[0].value)
    assert SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_INT256, "Value out of bounds"
    shift_len = ops[1].value
    return value >> shift_len


def _evm_not(ops: list[IROperand]) -> int:
    value = ops[0].value
    assert 0 <= value <= SizeLimits.MAX_UINT256, "Value out of bounds"
    return SizeLimits.MAX_UINT256 ^ value


ARITHMETIC_OPS: dict[str, Callable[[list[IROperand]], int]] = {
    "add": _wrap_binop(operator.add),
    "sub": _wrap_binop(operator.sub),
    "mul": _wrap_binop(operator.mul),
    "div": _wrap_binop(evm_div),
    "sdiv": _wrap_signed_binop(evm_div),
    "mod": _wrap_binop(evm_mod),
    "smod": _wrap_signed_binop(evm_mod),
    "exp": _wrap_binop(evm_pow),
    "eq": _wrap_binop(operator.eq),
    "ne": _wrap_binop(operator.ne),
    "lt": _wrap_binop(operator.lt),
    "le": _wrap_binop(operator.le),
    "gt": _wrap_binop(operator.gt),
    "ge": _wrap_binop(operator.ge),
    "slt": _wrap_signed_binop(operator.lt),
    "sle": _wrap_signed_binop(operator.le),
    "sgt": _wrap_signed_binop(operator.gt),
    "sge": _wrap_signed_binop(operator.ge),
    "or": _wrap_binop(operator.or_),
    "and": _wrap_binop(operator.and_),
    "xor": _wrap_binop(operator.xor),
    "not": _evm_not,
    "signextend": _evm_signextend,
    "iszero": _evm_iszero,
    "shr": _evm_shr,
    "shl": _evm_shl,
    "sar": _evm_sar,
    "store": lambda ops: ops[0].value,
}

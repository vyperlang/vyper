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
    assert isinstance(value, int)
    return unsigned_to_signed(value, 256)


def _signed_to_unsigned(value: int) -> int:
    assert isinstance(value, int)
    return signed_to_unsigned(value, 256)


def _wrap_signed_binop(operation):
    def wrapper(ops: list[IROperand]) -> int:
        assert len(ops) == 2
        first = _unsigned_to_signed(ops[1].value)
        second = _unsigned_to_signed(ops[0].value)
        return _signed_to_unsigned(operation(first, second))

    return wrapper


def _wrap_binop(operation):
    def wrapper(ops: list[IROperand]) -> int:
        assert len(ops) == 2
        first = _signed_to_unsigned(ops[1].value)
        second = _signed_to_unsigned(ops[0].value)
        ret = operation(first, second)
        return ret & SizeLimits.MAX_UINT256

    return wrapper


def _wrap_unop(operation):
    def wrapper(ops: list[IROperand]) -> int:
        assert len(ops) == 1
        value = _signed_to_unsigned(ops[0].value)
        ret = operation(value)
        return ret & SizeLimits.MAX_UINT256

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


def _evm_not(value: int) -> int:
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
    "not": _wrap_unop(_evm_not),
    "signextend": _wrap_binop(_evm_signextend),
    "iszero": _wrap_unop(_evm_iszero),
    "shr": _wrap_binop(_evm_shr),
    "shl": _wrap_binop(_evm_shl),
    "sar": _wrap_signed_binop(_evm_sar),
    "store": lambda ops: ops[0].value,
}

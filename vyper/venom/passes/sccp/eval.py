import operator
from typing import Callable

from vyper.utils import (
    SizeLimits,
    evm_div,
    evm_mod,
    evm_not,
    evm_pow,
    signed_to_unsigned,
    unsigned_to_signed,
)
from vyper.venom.basicblock import IRLiteral


def _unsigned_to_signed(value: int) -> int:
    assert isinstance(value, int)
    return unsigned_to_signed(value, 256)


def _signed_to_unsigned(value: int) -> int:
    assert isinstance(value, int)
    return signed_to_unsigned(value, 256)


def _wrap_signed_binop(operation):
    def wrapper(ops: list[IRLiteral]) -> int:
        assert len(ops) == 2
        first = _unsigned_to_signed(ops[1].value)
        second = _unsigned_to_signed(ops[0].value)
        return _signed_to_unsigned(operation(first, second))

    return wrapper


def _wrap_binop(operation):
    def wrapper(ops: list[IRLiteral]) -> int:
        assert len(ops) == 2
        first = _signed_to_unsigned(ops[1].value)
        second = _signed_to_unsigned(ops[0].value)
        ret = operation(first, second)
        # TODO: use wrap256 here
        return ret & SizeLimits.MAX_UINT256

    return wrapper


def _wrap_ternop(operation):
    def wrapper(ops: list[IRLiteral]) -> int:
        assert len(ops) == 3
        first = _signed_to_unsigned(ops[-1].value)
        second = _signed_to_unsigned(ops[-2].value)
        third = _signed_to_unsigned(ops[-3].value)
        ret = operation(first, second, third)
        return ret & SizeLimits.MAX_UINT256

    return wrapper


def _wrap_unop(operation):
    def wrapper(ops: list[IRLiteral]) -> int:
        assert len(ops) == 1
        value = _signed_to_unsigned(ops[0].value)
        ret = operation(value)
        # TODO: use wrap256 here
        return ret & SizeLimits.MAX_UINT256

    return wrapper


def _evm_addmod(a: int, b: int, N: int) -> int:
    """EVM ADDMOD: (a + b) % N, returns 0 if N == 0"""
    if N == 0:
        return 0
    return (a + b) % N


def _evm_mulmod(a: int, b: int, N: int) -> int:
    """EVM MULMOD: (a * b) % N, returns 0 if N == 0"""
    if N == 0:
        return 0
    return (a * b) % N


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
    # TODO: refactor to use wrap256
    return (value << shift_len) & SizeLimits.MAX_UINT256


def _evm_sar(shift_len: int, value: int) -> int:
    # shift_len is unsigned, value is signed
    # For large shifts (>= 256), result is 0 if value >= 0, else -1
    assert SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_INT256, "Value out of bounds"
    assert 0 <= shift_len <= SizeLimits.MAX_UINT256, "Shift out of bounds"
    if shift_len >= 256:
        return -1 if value < 0 else 0
    return value >> shift_len


def _evm_byte(index: int, value: int) -> int:
    """EVM BYTE: extract the index-th byte (big-endian) from value.

    byte(N, x) returns the N-th byte from the high end.
    When N >= 32, the result is always 0.
    """
    if index >= 32:
        return 0
    shift = (31 - index) * 8
    return (value >> shift) & 0xFF


def _wrap_sar(operation):
    """Special wrapper for SAR: shift_len is unsigned, value is signed."""

    def wrapper(ops: list[IRLiteral]) -> int:
        assert len(ops) == 2
        # ops[1] is shift_len (unsigned), ops[0] is value (signed)
        shift_len = _signed_to_unsigned(ops[1].value)  # normalize to unsigned
        value = _unsigned_to_signed(_signed_to_unsigned(ops[0].value))  # normalize to signed
        return _signed_to_unsigned(operation(shift_len, value))

    return wrapper


ARITHMETIC_OPS: dict[str, Callable[[list[IRLiteral]], int]] = {
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
    "sar": _wrap_sar(_evm_sar),
    "addmod": _wrap_ternop(_evm_addmod),
    "mulmod": _wrap_ternop(_evm_mulmod),
    "byte": _wrap_binop(_evm_byte),
}


def eval_arith(opcode: str, ops: list[IRLiteral]) -> int:
    fn = ARITHMETIC_OPS[opcode]
    return fn(ops)



import operator

from vyper.utils import SizeLimits, evm_div, evm_mod, evm_pow
from vyper.venom.basicblock import IROperand

def _unsigned_to_signed(value: int) -> int:
    if value <= SizeLimits.MAX_INT256:
        return value
    else:
        return value - SizeLimits.CEILING_UINT256
    
def _signed_to_unsigned(value: int) -> int:
    if value >= 0:
        return value
    else:
        return value + SizeLimits.CEILING_UINT256
    

def _wrap_uint_unaop(operation) -> int:
    def wrapper(ops: list[IROperand]):
        return (operation(ops[0].value)) & SizeLimits.MAX_UINT256
    return wrapper

def _wrap_int_binop(operation) -> int:
    def wrapper(ops: list[IROperand]):
        first = _unsigned_to_signed(ops[0].value)
        second = _unsigned_to_signed(ops[1].value)
        return _signed_to_unsigned(operation(first, second))
    return wrapper

def _wrap_uint_binop(operation) -> int:
    def wrapper(ops: list[IROperand]):
        first = ops[0].value
        second = ops[1].value
        return (operation(first, second)) & SizeLimits.MAX_UINT256
    return wrapper

def _evm_signextend(ops: list[IROperand]) -> int:
    bits = ops[0].value
    value = ops[1].value

    if bits > 31:
        return value

    bits = bits * 8 + 7
    sign_bit = 1 << bits
    if value & sign_bit:
        value |= SizeLimits.MAX_UINT256 - sign_bit
    else:
        value &= sign_bit - 1

    return value

def _evm_iszero(ops: list[IROperand]) -> int:
    return 1 if ops[0].value == 0 else 0

ARITHMETIC_OPS = {
    "add": _wrap_uint_binop(operator.add),
    "sub": _wrap_uint_binop(operator.sub),
    "mul": _wrap_uint_binop(operator.mul),
    "div": _wrap_uint_binop(evm_div),
    "sdiv": _wrap_uint_binop(evm_div),
    "mod": _wrap_uint_binop(evm_mod),
    "smod": _wrap_uint_binop(evm_mod),
    "exp": _wrap_uint_binop(evm_pow),

    "eq": _wrap_uint_binop(operator.eq),
    "ne": _wrap_uint_binop(operator.ne),
    "lt": _wrap_uint_binop(operator.lt),
    "le": _wrap_uint_binop(operator.le),
    "gt": _wrap_uint_binop(operator.gt),
    "ge": _wrap_uint_binop(operator.ge),
    "slt": _wrap_int_binop(operator.lt),
    "sle": _wrap_int_binop(operator.le),
    "sgt": _wrap_int_binop(operator.gt),
    "sge": _wrap_int_binop(operator.ge),
    
    "or": _wrap_uint_binop(operator.or_),
    "and": _wrap_uint_binop(operator.and_),
    "xor": _wrap_uint_binop(operator.xor),
    "not": _wrap_uint_unaop(operator.not_),
    
    "signextend": _evm_signextend,
    "iszero": _evm_iszero,
    "store": lambda ops: ops[0],
}


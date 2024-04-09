

import operator

from vyper.utils import SizeLimits, evm_div, evm_mod, evm_pow
from vyper.venom.basicblock import IROperand

def _wrap_int_binop(operation) -> int:
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

ARITHMETIC_OPS = {
    "add": _wrap_int_binop(operator.add),
    "sub": _wrap_int_binop(operator.sub),
    "mul": _wrap_int_binop(operator.mul),
    "div": _wrap_int_binop(evm_div),
    "sdiv": _wrap_int_binop(evm_div),
    "mod": _wrap_int_binop(evm_mod),
    "smod": _wrap_int_binop(evm_mod),
    "exp": _wrap_int_binop(evm_pow),
    "eq": _wrap_int_binop(operator.eq),
    "ne": _wrap_int_binop(operator.ne),
    "lt": _wrap_int_binop(operator.lt),
    "le": _wrap_int_binop(operator.le),
    "gt": _wrap_int_binop(operator.gt),
    "ge": _wrap_int_binop(operator.ge),
    "slt": _wrap_int_binop(operator.lt),
    "sle": _wrap_int_binop(operator.le),
    "sgt": _wrap_int_binop(operator.gt),
    "sge": _wrap_int_binop(operator.ge),
    "or": _wrap_int_binop(operator.or_),
    "and": _wrap_int_binop(operator.and_),
    "xor": _wrap_int_binop(operator.xor),
    "signextend": _evm_signextend,
}


import operator
from typing import Callable

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
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable


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


def _wrap_abstract_value(
    abs_operation: Callable[[list[IROperand]], IRLiteral | None], lit_operation
):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        abs_res = abs_operation(ops)
        if abs_res is not None:
            return abs_res
        if all(isinstance(op, IRLiteral) for op in ops):
            return lit_operation(ops)
        return None

    return wrapper


def _wrap_lit(oper):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        if all(isinstance(op, IRLiteral) for op in ops):
            return oper(ops)
        return None

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


def _var_eq(ops: list[IROperand]) -> IRLiteral | None:
    assert len(ops) == 2
    if (
        isinstance(ops[0], IRVariable)
        and isinstance(ops[1], IRVariable)
        and ops[0].name == ops[1].name
    ):
        return IRLiteral(1)
    return None


def _var_ne(ops: list[IROperand]) -> IRLiteral | None:
    assert len(ops) == 2
    if (
        isinstance(ops[0], IRVariable)
        and isinstance(ops[1], IRVariable)
        and ops[0].name == ops[1].name
    ):
        return IRLiteral(0)
    return None


def _wrap_comparison(signed: bool, gt: bool, oper: Callable[[list[IROperand]], IRLiteral]):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        assert len(ops) == 2
        tmp = _var_ne(ops)
        if tmp is not None:
            return tmp

        if all(isinstance(op, IRLiteral) for op in ops):
            return _wrap_lit(oper)(ops)

        lo, hi = int_bounds(bits=256, signed=signed)
        if isinstance(ops[0], IRLiteral):
            if gt:
                never = hi
            else:
                never = lo
            if ops[0].value == never:
                return IRLiteral(0)
        if isinstance(ops[1], IRLiteral):
            if not gt:
                never = hi
            else:
                never = lo
            if ops[1].value == never:
                return IRLiteral(0)
        return None

    return wrapper


def _wrap_multiplicative(oper: Callable[[list[IROperand]], IRLiteral]):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        assert len(ops) == 2
        if all(isinstance(op, IRLiteral) for op in ops):
            return oper(ops)

        if isinstance(ops[0], IRLiteral) and ops[0].value == 0:
            return IRLiteral(0)

        if isinstance(ops[1], IRLiteral) and ops[1].value == 0:
            return IRLiteral(0)

        return None

    return wrapper


def _wrap_div(oper: Callable[[list[IROperand]], IRLiteral]):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        assert len(ops) == 2
        if all(isinstance(op, IRLiteral) for op in ops):
            return oper(ops)

        if isinstance(ops[0], IRLiteral) and ops[0].value == 0:
            return IRLiteral(0)

        return None

    return wrapper


def _wrap_mod(oper: Callable[[list[IROperand]], IRLiteral]):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        assert len(ops) == 2
        if isinstance(ops[0], IRLiteral) and ops[0].value == 1:
            return IRLiteral(0)

        return _wrap_div(oper)(ops)

    return wrapper


def _exp(ops) -> IRLiteral | None:
    if lit_eq(ops[0], 0):
        return IRLiteral(1)

    if lit_eq(ops[1], 1):
        return IRLiteral(1)

    return _wrap_lit(_wrap_binop(evm_pow))(ops)


def _wrap_self_inverse_op(oper: Callable[[list[IROperand]], IRLiteral]):
    def wrapper(ops: list[IROperand]) -> IRLiteral | None:
        assert len(ops) == 2
        res_eq = _var_eq(ops)
        if res_eq is not None:
            return IRLiteral(0)
        return _wrap_lit(oper)(ops)

    return wrapper


def _or_op(ops: list[IROperand]) -> IRLiteral | None:
    assert len(ops) == 2
    if all(isinstance(op, IRLiteral) for op in ops):
        return _wrap_binop(operator.or_)(ops)

    # x | 0xff..ff == 0xff..ff
    if any(lit_eq(op, SizeLimits.MAX_UINT256) for op in ops):
        return IRLiteral(SizeLimits.MAX_UINT256)

    return None


ARITHMETIC_OPS: dict[str, Callable[[list[IROperand]], IRLiteral | None]] = {
    "add": _wrap_lit(_wrap_binop(operator.add)),
    "sub": _wrap_self_inverse_op(_wrap_binop(operator.sub)),
    "mul": _wrap_multiplicative(_wrap_binop(operator.mul)),
    "div": _wrap_div(_wrap_binop(evm_div)),
    "sdiv": _wrap_div(_wrap_signed_binop(evm_div)),
    "mod": _wrap_mod(_wrap_binop(evm_mod)),
    "smod": _wrap_mod(_wrap_signed_binop(evm_mod)),
    "exp": _exp,
    "eq": _wrap_abstract_value(_var_eq, _wrap_binop(operator.eq)),
    "lt": _wrap_comparison(signed=False, gt=False, oper=_wrap_binop(operator.lt)),
    "gt": _wrap_comparison(signed=False, gt=True, oper=_wrap_binop(operator.gt)),
    "slt": _wrap_comparison(signed=True, gt=False, oper=_wrap_signed_binop(operator.lt)),
    "sgt": _wrap_comparison(signed=True, gt=True, oper=_wrap_signed_binop(operator.gt)),
    "or": _or_op,
    "and": _wrap_multiplicative(_wrap_binop(operator.and_)),
    "xor": _wrap_self_inverse_op(_wrap_binop(operator.xor)),
    "not": _wrap_lit(_wrap_unop(evm_not)),
    "signextend": _wrap_lit(_wrap_binop(_evm_signextend)),
    "iszero": _wrap_lit(_wrap_unop(_evm_iszero)),
    "shr": _wrap_lit(_wrap_binop(_evm_shr)),
    "shl": _wrap_lit(_wrap_binop(_evm_shl)),
    "sar": _wrap_lit(_wrap_signed_binop(_evm_sar)),
    "store": _wrap_lit(lambda ops: ops[0].value),
}


def eval_arith(opcode: str, ops: list[IROperand]) -> IRLiteral | None:
    fn = ARITHMETIC_OPS[opcode]
    return fn(ops)

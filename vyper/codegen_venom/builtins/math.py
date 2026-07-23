"""
Unsafe math built-in functions.

These operations skip overflow/underflow checks for performance.
- unsafe_add, unsafe_sub, unsafe_mul, unsafe_div
- pow_mod256 (unchecked exponentiation)
- uint256_addmod, uint256_mulmod (modular arithmetic)
"""

from __future__ import annotations

from vyper.codegen_venom.builtins._call import BuiltinLowerer, PreparedBuiltinCall
from vyper.venom.basicblock import IRLiteral, IROperand


def lower_unsafe_add(call: PreparedBuiltinCall) -> IROperand:
    """unsafe_add(a, b) - unchecked addition."""
    return _lower_unsafe_binop(call, "add")


def lower_unsafe_sub(call: PreparedBuiltinCall) -> IROperand:
    """unsafe_sub(a, b) - unchecked subtraction."""
    return _lower_unsafe_binop(call, "sub")


def lower_unsafe_mul(call: PreparedBuiltinCall) -> IROperand:
    """unsafe_mul(a, b) - unchecked multiplication."""
    return _lower_unsafe_binop(call, "mul")


def lower_unsafe_div(call: PreparedBuiltinCall) -> IROperand:
    """unsafe_div(a, b) - unchecked division."""
    return _lower_unsafe_binop(call, "div")


def _lower_unsafe_binop(call: PreparedBuiltinCall, op: str) -> IROperand:
    """
    Common implementation for unsafe binary operations.

    For sub-256-bit types, wraps the result appropriately:
    - Unsigned: mask to bit width
    - Signed: sign-extend
    """
    ctx = call.ctx
    b = ctx.builder

    a_val = call.word("a")
    b_val = call.word("b")
    typ = call.arg_type(0)

    # Use signed division for signed types
    if op == "div" and typ.is_signed:
        op = "sdiv"

    # Direct EVM operation
    op_method = getattr(b, op)
    result = op_method(a_val, b_val)

    # Wrap for sub-256-bit types
    if typ.bits < 256:
        if typ.is_signed:
            # Sign-extend: signextend(bytes-1, val)
            result = b.signextend(IRLiteral(typ.bits // 8 - 1), result)
        else:
            # Mask to bit width
            mask = (1 << typ.bits) - 1
            result = b.and_(result, IRLiteral(mask))

    return result


def lower_pow_mod256(call: PreparedBuiltinCall) -> IROperand:
    """
    pow_mod256(base, exp) - unchecked exponentiation mod 2^256.

    Uses EVM EXP opcode directly with no overflow checks.
    """
    ctx = call.ctx
    b = ctx.builder

    base = call.word("a")
    exp = call.word("b")

    return b.exp(base, exp)


def lower_uint256_addmod(call: PreparedBuiltinCall) -> IROperand:
    """
    uint256_addmod(a, b, c) - (a + b) % c without intermediate overflow.

    Uses EVM ADDMOD opcode which handles the 512-bit intermediate result.
    Reverts if c is zero.
    """
    ctx = call.ctx
    b = ctx.builder

    a_val = call.word("a")
    b_val = call.word("b")
    c_val = call.word("c")

    # Assert divisor is non-zero (EVM ADDMOD returns 0 on div by zero)
    b.assert_(c_val)

    return b.addmod(a_val, b_val, c_val)


def lower_uint256_mulmod(call: PreparedBuiltinCall) -> IROperand:
    """
    uint256_mulmod(a, b, c) - (a * b) % c without intermediate overflow.

    Uses EVM MULMOD opcode which handles the 512-bit intermediate result.
    Reverts if c is zero.
    """
    ctx = call.ctx
    b = ctx.builder

    a_val = call.word("a")
    b_val = call.word("b")
    c_val = call.word("c")

    # Assert divisor is non-zero (EVM MULMOD returns 0 on div by zero)
    b.assert_(c_val)

    return b.mulmod(a_val, b_val, c_val)


def lower_shift(call: PreparedBuiltinCall) -> IROperand:
    """
    shift(x, bits) - bit shift operation (deprecated in favor of << / >> operators).

    If bits < 0: right shift (sar for signed, shr for unsigned)
    If bits >= 0: left shift (shl)
    """
    ctx = call.ctx
    b = ctx.builder

    val = call.word("x")
    bits = call.word("_shift_bits")
    val_typ = call.arg_type(0)

    # Generalized right shift: sar for signed, shr for unsigned
    is_signed = val_typ.is_signed

    # Check if bits < 0 at runtime
    # EVM: slt(bits, 0) returns 1 if bits < 0
    is_negative = b.slt(bits, IRLiteral(0))

    # neg_bits = -bits = sub(0, bits)
    neg_bits = b.sub(IRLiteral(0), bits)

    # Right shift (when bits < 0)
    if is_signed:
        right_shifted = b.sar(neg_bits, val)
    else:
        right_shifted = b.shr(neg_bits, val)

    # Left shift (when bits >= 0)
    left_shifted = b.shl(bits, val)

    # Select based on sign of bits
    result = b.select(is_negative, right_shifted, left_shifted)

    return result


# Export handlers
HANDLERS = {
    "unsafe_add": BuiltinLowerer(lower_unsafe_add),
    "unsafe_sub": BuiltinLowerer(lower_unsafe_sub),
    "unsafe_mul": BuiltinLowerer(lower_unsafe_mul),
    "shift": BuiltinLowerer(lower_shift),
    "unsafe_div": BuiltinLowerer(lower_unsafe_div),
    "pow_mod256": BuiltinLowerer(lower_pow_mod256),
    "uint256_addmod": BuiltinLowerer(lower_uint256_addmod),
    "uint256_mulmod": BuiltinLowerer(lower_uint256_mulmod),
}

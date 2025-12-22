"""
Unsafe math built-in functions.

These operations skip overflow/underflow checks for performance.
- unsafe_add, unsafe_sub, unsafe_mul, unsafe_div
- pow_mod256 (unchecked exponentiation)
- uint256_addmod, uint256_mulmod (modular arithmetic)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_unsafe_add(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """unsafe_add(a, b) - unchecked addition."""
    return _lower_unsafe_binop(node, ctx, "add")


def lower_unsafe_sub(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """unsafe_sub(a, b) - unchecked subtraction."""
    return _lower_unsafe_binop(node, ctx, "sub")


def lower_unsafe_mul(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """unsafe_mul(a, b) - unchecked multiplication."""
    return _lower_unsafe_binop(node, ctx, "mul")


def lower_unsafe_div(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """unsafe_div(a, b) - unchecked division."""
    return _lower_unsafe_binop(node, ctx, "div")


def _lower_unsafe_binop(
    node: vy_ast.Call, ctx: VenomCodegenContext, op: str
) -> IROperand:
    """
    Common implementation for unsafe binary operations.

    For sub-256-bit types, wraps the result appropriately:
    - Unsigned: mask to bit width
    - Signed: sign-extend
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    a_val = Expr(node.args[0], ctx).lower()
    b_val = Expr(node.args[1], ctx).lower()
    typ = node.args[0]._metadata["type"]

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


def lower_pow_mod256(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    pow_mod256(base, exp) - unchecked exponentiation mod 2^256.

    Uses EVM EXP opcode directly with no overflow checks.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    base = Expr(node.args[0], ctx).lower()
    exp = Expr(node.args[1], ctx).lower()

    return b.exp(base, exp)


def lower_uint256_addmod(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    uint256_addmod(a, b, c) - (a + b) % c without intermediate overflow.

    Uses EVM ADDMOD opcode which handles the 512-bit intermediate result.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    a_val = Expr(node.args[0], ctx).lower()
    b_val = Expr(node.args[1], ctx).lower()
    c_val = Expr(node.args[2], ctx).lower()

    return b.addmod(a_val, b_val, c_val)


def lower_uint256_mulmod(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    uint256_mulmod(a, b, c) - (a * b) % c without intermediate overflow.

    Uses EVM MULMOD opcode which handles the 512-bit intermediate result.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    a_val = Expr(node.args[0], ctx).lower()
    b_val = Expr(node.args[1], ctx).lower()
    c_val = Expr(node.args[2], ctx).lower()

    return b.mulmod(a_val, b_val, c_val)


# Export handlers
HANDLERS = {
    "unsafe_add": lower_unsafe_add,
    "unsafe_sub": lower_unsafe_sub,
    "unsafe_mul": lower_unsafe_mul,
    "unsafe_div": lower_unsafe_div,
    "pow_mod256": lower_pow_mod256,
    "uint256_addmod": lower_uint256_addmod,
    "uint256_mulmod": lower_uint256_mulmod,
}

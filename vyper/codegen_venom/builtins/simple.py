"""
Simple built-in functions: len, empty, min, max, abs
"""

from vyper import ast as vy_ast
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral, IROperand

if False:  # TYPE_CHECKING
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_len(node: vy_ast.Call, ctx: "VenomCodegenContext") -> IROperand:
    """
    len(x) for dynamic arrays, bytes, strings.

    Returns the length stored at the pointer (first word).
    Special case: len(msg.data) returns calldatasize.
    """
    from vyper.codegen_venom.expr import Expr

    arg_node = node.args[0]

    # Special case: len(msg.data) returns calldatasize
    if isinstance(arg_node, vy_ast.Attribute) and arg_node.attr == "data":
        if isinstance(arg_node.value, vy_ast.Name) and arg_node.value.id == "msg":
            return ctx.builder.calldatasize()

    # For bytes/string/DynArray: length is stored at pointer
    arg = Expr(arg_node, ctx).lower()
    return ctx.builder.mload(arg)


def lower_empty(node: vy_ast.Call, ctx: "VenomCodegenContext") -> IROperand:
    """
    empty(T) returns zero-initialized value of type T.

    For primitives: returns 0
    For complex types: allocates zeroed memory
    """
    typ = node._metadata["type"]

    if typ._is_prim_word:
        return IRLiteral(0)
    else:
        # Allocate memory buffer - memory is zero-initialized
        return ctx.new_internal_variable(typ)


def lower_min(node: vy_ast.Call, ctx: "VenomCodegenContext") -> IROperand:
    """min(a, b) - returns smaller of two values."""
    return _lower_minmax(node, ctx, is_max=False)


def lower_max(node: vy_ast.Call, ctx: "VenomCodegenContext") -> IROperand:
    """max(a, b) - returns larger of two values."""
    return _lower_minmax(node, ctx, is_max=True)


def _lower_minmax(
    node: vy_ast.Call, ctx: "VenomCodegenContext", is_max: bool
) -> IROperand:
    """
    Common implementation for min/max.

    Uses select: if (a op b) then a else b
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    a_val = Expr(node.args[0], ctx).lower()
    b_val = Expr(node.args[1], ctx).lower()
    typ = node.args[0]._metadata["type"]

    # Choose comparison - signed for most types, unsigned only for uint256
    if typ == UINT256_T:
        cmp_result = b.gt(a_val, b_val) if is_max else b.lt(a_val, b_val)
    else:
        cmp_result = b.sgt(a_val, b_val) if is_max else b.slt(a_val, b_val)

    return b.select(cmp_result, a_val, b_val)


def lower_abs(node: vy_ast.Call, ctx: "VenomCodegenContext") -> IROperand:
    """
    abs(x) for int256 only.

    Returns absolute value, with overflow check for MIN_INT256.
    abs(-2^255) would overflow since 2^255 > MAX_INT256.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    val = Expr(node.args[0], ctx).lower()

    # Compute negation: neg_val = 0 - val
    neg_val = b.sub(IRLiteral(0), val)

    # Check for MIN_INT256 overflow: if val < 0 and val == neg_val, it's MIN_INT
    # (Only MIN_INT satisfies x == -x for x != 0)
    is_negative = b.slt(val, IRLiteral(0))
    is_min_int = b.eq(val, neg_val)
    bad = b.and_(is_negative, is_min_int)
    b.assert_(b.iszero(bad))

    # Return neg_val if negative, else val
    return b.select(is_negative, neg_val, val)


# Export handlers
HANDLERS = {
    "len": lower_len,
    "empty": lower_empty,
    "min": lower_min,
    "max": lower_max,
    "abs": lower_abs,
}

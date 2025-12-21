"""
Tests for Expr comparison/boolean lowering in codegen_venom.

These tests use function parameters (Name nodes) to force runtime operations.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.expr import Expr
from vyper.compiler.phases import CompilerData
from vyper.venom.basicblock import IRVariable
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _get_expr_context(source: str) -> tuple[VenomCodegenContext, "vy_ast.VyperNode"]:
    """
    Compile source and return (VenomCodegenContext, expression_node).

    The source should be a function with a single return statement.
    Returns the expression node from that return.
    """
    compiler_data = CompilerData(source)
    module_ast = compiler_data.annotated_vyper_module
    module_t = module_ast._metadata["type"]

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    codegen_ctx = VenomCodegenContext(module_t, builder)

    # Get the function definition (skip module-level items like flags)
    func_def = None
    for item in module_ast.body:
        if hasattr(item, "args"):  # FunctionDef has args
            func_def = item
            break
    assert func_def is not None, "No function found in source"

    # Register function parameters in codegen context
    # This simulates what the full function codegen would do
    func_t = func_def._metadata["func_type"]
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return_stmt = func_def.body[0]
    expr_node = return_stmt.value

    return codegen_ctx, expr_node


class TestComparisonOps:
    def test_lt_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> bool:
    return a < b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_gt_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> bool:
    return a > b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_le_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> bool:
    return a <= b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_ge_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> bool:
    return a >= b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_eq_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> bool:
    return a == b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_neq_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> bool:
    return a != b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestSignedComparison:
    def test_lt_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> bool:
    return a < b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_gt_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> bool:
    return a > b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_le_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> bool:
    return a <= b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_ge_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> bool:
    return a >= b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestBoolOps:
    def test_and(self):
        source = """
# @version ^0.4.0
@external
def foo(a: bool, b: bool) -> bool:
    return a and b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_or(self):
        source = """
# @version ^0.4.0
@external
def foo(a: bool, b: bool) -> bool:
    return a or b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_and_three(self):
        source = """
# @version ^0.4.0
@external
def foo(a: bool, b: bool, c: bool) -> bool:
    return a and b and c
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_or_three(self):
        source = """
# @version ^0.4.0
@external
def foo(a: bool, b: bool, c: bool) -> bool:
    return a or b or c
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestFlagMembership:
    def test_in_flag(self):
        source = """
# @version ^0.4.0
flag Status:
    ACTIVE
    PAUSED
    STOPPED

@external
def foo(s: Status, check: Status) -> bool:
    return s in check
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_not_in_flag(self):
        source = """
# @version ^0.4.0
flag Status:
    ACTIVE
    PAUSED
    STOPPED

@external
def foo(s: Status, check: Status) -> bool:
    return s not in check
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

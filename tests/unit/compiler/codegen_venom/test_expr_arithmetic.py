"""
Tests for Expr arithmetic/bitwise/unary lowering in codegen_venom.

These tests use function parameters (Name nodes) to force runtime operations.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.expr import Expr
from vyper.compiler.phases import CompilerData
from vyper.venom.basicblock import IRLiteral, IRVariable
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

    # Get first function definition
    func_def = module_ast.body[0]

    # Register function parameters in codegen context
    func_t = func_def._metadata["func_type"]
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return_stmt = func_def.body[0]
    expr_node = return_stmt.value

    return codegen_ctx, expr_node


class TestBitwiseOps:
    def test_and(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a & b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_or(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a | b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_xor(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a ^ b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)


class TestShiftOps:
    def test_lshift(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a << b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_rshift_unsigned(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a >> b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_rshift_signed(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: uint256) -> int256:
    return a >> b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)


class TestArithmeticOps:
    def test_add_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a + b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_sub_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a - b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_mul_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a * b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_floordiv_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a // b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_mod_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a % b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)


class TestDecimalOps:
    def test_add_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a + b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_sub_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a - b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_mul_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a * b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_div_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a / b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)


class TestPower:
    def test_pow_literal_base(self):
        source = """
# @version ^0.4.0
@external
def foo(n: uint256) -> uint256:
    return 2 ** n
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_pow_literal_exp(self):
        source = """
# @version ^0.4.0
@external
def foo(n: uint256) -> uint256:
    return n ** 3
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)


class TestUnaryOps:
    def test_not_bool(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bool) -> bool:
    return not x
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_invert_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return ~x
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_usub_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: int256) -> int256:
    return -x
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)


class TestInt256Special:
    def test_add_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return a + b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

    def test_mul_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return a * b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower_value()

        assert isinstance(result, IRVariable)

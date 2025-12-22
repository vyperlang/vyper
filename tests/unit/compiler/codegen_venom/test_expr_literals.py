"""
Tests for Expr literal lowering in codegen_venom.

These tests verify that literal expressions (integers, decimals, booleans,
addresses, bytesN, and byte/string data) are correctly lowered to Venom IR.
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

    # Get expression from first function's return statement
    func_def = module_ast.body[0]
    return_stmt = func_def.body[0]
    expr_node = return_stmt.value

    return codegen_ctx, expr_node


class TestIntLiteral:
    def test_simple_int(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return 42
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 42

    def test_zero(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return 0
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 0

    def test_large_int(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return 115792089237316195423570985008687907853269984665640564039457584007913129639935
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 2**256 - 1


class TestDecimalLiteral:
    def test_simple_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo() -> decimal:
    return 3.14
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        # 3.14 * 10^10 = 31400000000
        assert result.value == 31_400_000_000

    def test_zero_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo() -> decimal:
    return 0.0
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 0

    def test_negative_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo() -> decimal:
    return -1.5
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        # -1.5 * 10^10 = -15000000000
        assert result.value == -15_000_000_000

    def test_max_precision_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo() -> decimal:
    return 0.0000000001
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        # Smallest positive: 10^-10 * 10^10 = 1
        assert result.value == 1


class TestBoolLiteral:
    def test_true(self):
        source = """
# @version ^0.4.0
@external
def foo() -> bool:
    return True
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 1

    def test_false(self):
        source = """
# @version ^0.4.0
@external
def foo() -> bool:
    return False
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 0


class TestAddressLiteral:
    def test_address(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return 0xdEADBEeF00000000000000000000000000000000
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 0xDEADBEEF00000000000000000000000000000000

    def test_zero_address(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return 0x0000000000000000000000000000000000000000
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        assert result.value == 0


class TestBytesMHexLiteral:
    """Test hex literals that become bytesN types."""

    def test_bytes4(self):
        source = """
# @version ^0.4.0
@external
def foo() -> bytes4:
    return 0xDEADBEEF
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        # bytes4 is left-padded: 0xDEADBEEF << (28*8)
        expected = 0xDEADBEEF << (28 * 8)
        assert result.value == expected

    def test_bytes1(self):
        source = """
# @version ^0.4.0
@external
def foo() -> bytes1:
    return 0xFF
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        # bytes1: 0xFF << (31*8)
        expected = 0xFF << (31 * 8)
        assert result.value == expected

    def test_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo() -> bytes32:
    return 0x0102030405060708091011121314151617181920212223242526272829303132
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRLiteral)
        # bytes32: no shift needed (32 - 32 = 0)
        expected = 0x0102030405060708091011121314151617181920212223242526272829303132
        assert result.value == expected


class TestBytesLiteral:
    """Test dynamic bytes literals."""

    def test_empty_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo() -> Bytes[10]:
    return b""
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        # Returns pointer (IRVariable), not literal
        assert isinstance(result, IRVariable)

    def test_simple_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo() -> Bytes[10]:
    return b"hello"
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_long_bytes(self):
        """Test bytes spanning multiple 32-byte words."""
        source = """
# @version ^0.4.0
@external
def foo() -> Bytes[100]:
    return b"0123456789012345678901234567890123456789"
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestHexBytesLiteral:
    """Test hex bytes literals (x'...')."""

    def test_hexbytes(self):
        source = """
# @version ^0.4.0
@external
def foo() -> Bytes[4]:
    return x"DEADBEEF"
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestStringLiteral:
    """Test string literals."""

    def test_empty_string(self):
        source = """
# @version ^0.4.0
@external
def foo() -> String[10]:
    return ""
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_simple_string(self):
        source = """
# @version ^0.4.0
@external
def foo() -> String[20]:
    return "hello world"
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_long_string(self):
        """Test string spanning multiple 32-byte words."""
        source = """
# @version ^0.4.0
@external
def foo() -> String[100]:
    return "0123456789012345678901234567890123456789"
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

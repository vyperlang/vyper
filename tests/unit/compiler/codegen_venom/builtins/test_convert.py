"""
Tests for convert() built-in function.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.codegen_venom.value import VyperValue
from vyper.venom.basicblock import IRLiteral, IRVariable

from .conftest import get_expr_context


class TestConvertToBool:
    def test_int_to_bool(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> bool:
    return convert(x, bool)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_address_to_bool(self):
        source = """
# @version ^0.4.0
@external
def foo(x: address) -> bool:
    return convert(x, bool)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytes32_to_bool(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes32) -> bool:
    return convert(x, bool)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)


class TestConvertToInt:
    def test_bool_to_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bool) -> uint256:
    return convert(x, uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        # Bool is 0 or 1, fits in any int
        assert isinstance(result, IRVariable)

    def test_address_to_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: address) -> uint256:
    return convert(x, uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytes32_to_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes32) -> uint256:
    return convert(x, uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytes32_to_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes32) -> int256:
    return convert(x, int256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_int256_to_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: int256) -> uint256:
    return convert(x, uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_uint256_to_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> int256:
    return convert(x, int256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytes4_to_uint32(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes4) -> uint32:
    return convert(x, uint32)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)


class TestConvertToAddress:
    def test_bytes32_to_address(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes32) -> address:
    return convert(x, address)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_uint256_to_address(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> address:
    return convert(x, address)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytes20_to_address(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes20) -> address:
    return convert(x, address)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)


class TestConvertToBytesM:
    def test_uint256_to_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> bytes32:
    return convert(x, bytes32)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_address_to_bytes20(self):
        source = """
# @version ^0.4.0
@external
def foo(x: address) -> bytes20:
    return convert(x, bytes20)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytes32_to_bytes4(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bytes32) -> bytes4:
    return convert(x, bytes4)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_bytesm_downcast_emits_clamp(self):
        """
        Regression test: bytesM downcast should emit an assertion (clamp)
        rather than silently truncating via masking.

        The generated code should contain shl to check that low bytes are zero.
        """
        source = """
# @version ^0.4.0
@external
def foo(x: bytes4) -> bytes2:
    return convert(x, bytes2)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

        # Verify that the generated IR contains an assertion (shl + iszero + assert)
        # The clamp pattern is: shl(16, val) -> iszero -> assert
        fn = ctx.builder.fn
        found_shl = False
        found_assert = False
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "shl":
                    # Check for shl with shift amount of 16 (bytes2 * 8)
                    for op in inst.operands:
                        if getattr(op, "value", None) == 16:
                            found_shl = True
                            break
                if inst.opcode == "assert":
                    found_assert = True

        assert found_shl, "Expected shl(16, ...) instruction for bytes_clamp"
        assert found_assert, "Expected assert instruction for bytes_clamp"


class TestConvertToDecimal:
    def test_int256_to_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo(x: int256) -> decimal:
    return convert(x, decimal)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_uint256_to_decimal(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> decimal:
    return convert(x, decimal)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)


class TestConvertBytestrings:
    def test_bytes_to_string(self):
        source = """
# @version ^0.4.0
@external
def foo(x: Bytes[100]) -> String[100]:
    return convert(x, String[100])
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, VyperValue)
        assert isinstance(result.operand, IRVariable)

    def test_string_to_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(x: String[100]) -> Bytes[100]:
    return convert(x, Bytes[100])
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, VyperValue)
        assert isinstance(result.operand, IRVariable)

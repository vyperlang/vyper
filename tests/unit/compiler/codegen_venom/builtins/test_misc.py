"""
Tests for miscellaneous builtin handlers.
"""

import pytest

from vyper.codegen_venom.builtins import BUILTIN_HANDLERS
from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRLiteral

from .conftest import get_expr_context


class TestMiscHandlerRegistration:
    """Test that misc builtin handlers are properly registered."""

    def test_ecrecover_registered(self):
        assert "ecrecover" in BUILTIN_HANDLERS

    def test_ecadd_registered(self):
        assert "ecadd" in BUILTIN_HANDLERS

    def test_ecmul_registered(self):
        assert "ecmul" in BUILTIN_HANDLERS

    def test_blockhash_registered(self):
        assert "blockhash" in BUILTIN_HANDLERS

    def test_blobhash_registered(self):
        assert "blobhash" in BUILTIN_HANDLERS

    def test_floor_registered(self):
        assert "floor" in BUILTIN_HANDLERS

    def test_ceil_registered(self):
        assert "ceil" in BUILTIN_HANDLERS

    def test_as_wei_value_registered(self):
        assert "as_wei_value" in BUILTIN_HANDLERS

    def test_min_value_registered(self):
        assert "min_value" in BUILTIN_HANDLERS

    def test_max_value_registered(self):
        assert "max_value" in BUILTIN_HANDLERS

    def test_epsilon_registered(self):
        assert "epsilon" in BUILTIN_HANDLERS

    def test_isqrt_registered(self):
        assert "isqrt" in BUILTIN_HANDLERS

    def test_breakpoint_registered(self):
        assert "breakpoint" in BUILTIN_HANDLERS


class TestMinMaxValue:
    """Test min_value/max_value builtin compilation."""

    def test_min_value_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return min_value(uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRLiteral)
        assert result.value == 0

    def test_max_value_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return max_value(uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRLiteral)
        assert result.value == 2**256 - 1

    def test_min_value_int256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> int256:
    return min_value(int256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRLiteral)
        assert result.value == -(2**255)

    def test_max_value_int256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> int256:
    return max_value(int256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRLiteral)
        assert result.value == 2**255 - 1


class TestEpsilon:
    """Test epsilon builtin compilation."""

    def test_epsilon(self):
        source = """
# @version ^0.4.0
@external
def foo() -> decimal:
    return epsilon(decimal)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRLiteral)
        assert result.value == 1  # Smallest decimal unit

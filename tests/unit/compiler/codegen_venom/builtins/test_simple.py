"""
Tests for simple built-in functions: len, empty, min, max, abs.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRLiteral, IRVariable

from .conftest import get_expr_context


class TestLen:
    def test_len_dynarray(self):
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[uint256, 10]) -> uint256:
    return len(arr)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_len_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> uint256:
    return len(b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_len_string(self):
        source = """
# @version ^0.4.0
@external
def foo(s: String[100]) -> uint256:
    return len(s)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestEmpty:
    def test_empty_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return empty(uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRLiteral)
        assert result.value == 0

    def test_empty_address(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return empty(address)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRLiteral)
        assert result.value == 0


class TestMinMax:
    def test_min_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return min(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_max_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return max(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_min_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return min(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_max_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return max(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestAbs:
    def test_abs_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: int256) -> int256:
    return abs(x)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

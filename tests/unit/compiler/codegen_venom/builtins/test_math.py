"""
Tests for math built-in functions: unsafe_*, pow_mod256, addmod, mulmod.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRVariable

from .conftest import get_expr_context


class TestUnsafeMath:
    def test_unsafe_add(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_add(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_unsafe_sub(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_sub(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_unsafe_mul(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_mul(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_unsafe_div(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_div(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_unsafe_div_signed(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return unsafe_div(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)


class TestPowMod:
    def test_pow_mod256(self):
        source = """
# @version ^0.4.0
@external
def foo(base: uint256, exp: uint256) -> uint256:
    return pow_mod256(base, exp)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)


class TestModArithmetic:
    def test_uint256_addmod(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return uint256_addmod(a, b, c)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

    def test_uint256_mulmod(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return uint256_mulmod(a, b, c)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

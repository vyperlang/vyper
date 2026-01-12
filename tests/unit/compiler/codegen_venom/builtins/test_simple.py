"""
Tests for simple built-in functions: empty.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRLiteral

from .conftest import get_expr_context


class TestEmpty:
    def test_empty_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return empty(uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
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
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRLiteral)
        assert result.value == 0

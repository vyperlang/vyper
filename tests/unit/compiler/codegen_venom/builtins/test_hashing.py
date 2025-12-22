"""
Tests for hashing built-in functions: keccak256, sha256.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRVariable

from .conftest import get_expr_context


class TestKeccak256:
    def test_keccak256_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> bytes32:
    return keccak256(data)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_keccak256_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(data: bytes32) -> bytes32:
    return keccak256(data)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_keccak256_string(self):
        source = """
# @version ^0.4.0
@external
def foo(data: String[100]) -> bytes32:
    return keccak256(data)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestSha256:
    def test_sha256_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> bytes32:
    return sha256(data)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_sha256_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(data: bytes32) -> bytes32:
    return sha256(data)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_sha256_string(self):
        source = """
# @version ^0.4.0
@external
def foo(data: String[100]) -> bytes32:
    return sha256(data)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

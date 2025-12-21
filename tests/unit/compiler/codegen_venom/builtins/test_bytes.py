"""
Tests for byte manipulation built-in functions: concat, slice, extract32.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRVariable

from .conftest import get_expr_context


class TestConcat:
    def test_concat_two_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(a: Bytes[50], b: Bytes[50]) -> Bytes[100]:
    return concat(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_concat_three_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(a: Bytes[30], b: Bytes[30], c: Bytes[40]) -> Bytes[100]:
    return concat(a, b, c)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_concat_two_strings(self):
        source = """
# @version ^0.4.0
@external
def foo(a: String[50], b: String[50]) -> String[100]:
    return concat(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_concat_bytes_with_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(a: Bytes[50], b: bytes32) -> Bytes[82]:
    return concat(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_concat_bytes4_with_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(a: bytes4, b: Bytes[50]) -> Bytes[54]:
    return concat(a, b)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_concat_multiple_bytesM(self):
        source = """
# @version ^0.4.0
@external
def foo(a: bytes4, b: bytes8, c: bytes20) -> Bytes[32]:
    return concat(a, b, c)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestSlice:
    def test_slice_bytes_literal_args(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> Bytes[10]:
    return slice(b, 5, 10)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_slice_bytes_dynamic_start(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100], start: uint256) -> Bytes[10]:
    return slice(b, start, 10)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_slice_string(self):
        source = """
# @version ^0.4.0
@external
def foo(s: String[100]) -> String[20]:
    return slice(s, 0, 20)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_slice_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(b: bytes32) -> Bytes[16]:
    return slice(b, 0, 16)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_slice_msg_data(self):
        source = """
# @version ^0.4.0
@external
def foo() -> Bytes[32]:
    return slice(msg.data, 0, 32)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_slice_self_code(self):
        source = """
# @version ^0.4.0
@external
def foo() -> Bytes[32]:
    return slice(self.code, 0, 32)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_slice_extcode(self):
        source = """
# @version ^0.4.0
@external
def foo(addr: address) -> Bytes[32]:
    return slice(addr.code, 0, 32)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestExtract32:
    def test_extract32_default(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> bytes32:
    return extract32(b, 0)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_extract32_with_offset(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100], pos: uint256) -> bytes32:
    return extract32(b, pos)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_extract32_output_type_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> int256:
    return extract32(b, 0, output_type=int256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_extract32_output_type_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> uint256:
    return extract32(b, 0, output_type=uint256)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_extract32_output_type_address(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> address:
    return extract32(b, 0, output_type=address)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

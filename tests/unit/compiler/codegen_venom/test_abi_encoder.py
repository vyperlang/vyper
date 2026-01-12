"""
Unit tests for ABI encoding in Venom codegen.

Tests the internal abi_encode_to_buf() function fast path that returns
IRLiteral with correct static size.
"""

import pytest

from vyper.codegen_venom.abi import abi_encode_to_buf
from vyper.semantics.types import SArrayT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral

from .builtins.conftest import get_expr_context


class TestABIEncodeFastPath:
    """Test fast path - static types with matching Vyper/ABI layout."""

    def test_encode_uint256(self):
        """Single uint256 - uses fast path (static, matches layout)."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        # Get the x variable pointer
        src_ptr = ctx.lookup("x").value.operand
        dst_buf = ctx.allocate_buffer(32)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, UINT256_T, returns_len=True)
        # Fast path returns literal 32
        assert isinstance(result, IRLiteral)
        assert result.value == 32

    def test_encode_static_array(self):
        """Static array of uint256 - uses fast path."""
        source = """
# @version ^0.4.0
@external
def foo(arr: uint256[3]) -> uint256[3]:
    return arr
"""
        ctx, node = get_expr_context(source)
        src_ptr = ctx.lookup("arr").value.operand
        arr_typ = SArrayT(UINT256_T, 3)
        dst_buf = ctx.allocate_buffer(96)  # 3 * 32 bytes

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, arr_typ, returns_len=True)
        # Fast path returns literal static size
        assert isinstance(result, IRLiteral)
        assert result.value == 96

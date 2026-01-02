"""
Unit tests for ABI encoding in Venom codegen.

Tests the internal abi_encode_to_buf() function that handles
ABI encoding of values for external function returns and abi_encode builtin.
"""

import pytest

from vyper.codegen_venom.abi import abi_encode_to_buf
from vyper.semantics.types import BytesT, DArrayT, SArrayT, StringT, TupleT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral, IRVariable

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
        src_ptr = ctx.lookup_ptr("x")
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
        src_ptr = ctx.lookup_ptr("arr")
        arr_typ = SArrayT(UINT256_T, 3)
        dst_buf = ctx.allocate_buffer(96)  # 3 * 32 bytes

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, arr_typ, returns_len=True)
        # Fast path returns literal static size
        assert isinstance(result, IRLiteral)
        assert result.value == 96


class TestABIEncodeBytestrings:
    """Test bytestring encoding (dynamic types)."""

    def test_encode_bytes(self):
        """Bytes type - requires zero padding."""
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> Bytes[100]:
    return data
"""
        ctx, node = get_expr_context(source)
        src_ptr = ctx.lookup_ptr("data")
        typ = BytesT(100)
        max_size = typ.abi_type.size_bound()
        dst_buf = ctx.allocate_buffer(max_size)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, typ, returns_len=True)
        # Dynamic type returns IRVariable (computed at runtime)
        assert isinstance(result, IRVariable)

    def test_encode_string(self):
        """String type - similar to bytes."""
        source = """
# @version ^0.4.0
@external
def foo(data: String[100]) -> String[100]:
    return data
"""
        ctx, node = get_expr_context(source)
        src_ptr = ctx.lookup_ptr("data")
        typ = StringT(100)
        max_size = typ.abi_type.size_bound()
        dst_buf = ctx.allocate_buffer(max_size)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, typ, returns_len=True)
        # Dynamic type returns IRVariable
        assert isinstance(result, IRVariable)


class TestABIEncodeComplexTypes:
    """Test complex type encoding (tuples, structs, arrays)."""

    def test_encode_static_tuple(self):
        """Tuple of static types - static encoding."""
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> (uint256, uint256):
    return (a, b)
"""
        ctx, node = get_expr_context(source)
        # Create a tuple in memory
        typ = TupleT([UINT256_T, UINT256_T])
        src_val = ctx.new_temporary_value(typ)
        dst_buf = ctx.allocate_buffer(64)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_val.operand, typ, returns_len=True)
        # Static tuple returns literal size
        assert isinstance(result, IRLiteral)
        assert result.value == 64

    def test_encode_tuple_with_dynamic_member(self):
        """Tuple containing dynamic type."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256, data: Bytes[32]) -> (uint256, Bytes[32]):
    return (x, data)
"""
        ctx, node = get_expr_context(source)
        typ = TupleT([UINT256_T, BytesT(32)])
        src_val = ctx.new_temporary_value(typ)
        max_size = typ.abi_type.size_bound()
        dst_buf = ctx.allocate_buffer(max_size)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_val.operand, typ, returns_len=True)
        # Dynamic content means runtime-computed length
        assert isinstance(result, IRVariable)


class TestABIEncodeDynArray:
    """Test dynamic array encoding."""

    def test_encode_dynarray_static_elements(self):
        """DynArray of static elements (uint256)."""
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[uint256, 10]) -> DynArray[uint256, 10]:
    return arr
"""
        ctx, node = get_expr_context(source)
        src_ptr = ctx.lookup_ptr("arr")
        typ = DArrayT(UINT256_T, 10)
        max_size = typ.abi_type.size_bound()
        dst_buf = ctx.allocate_buffer(max_size)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, typ, returns_len=True)
        # DynArray encoding has runtime-computed length
        assert isinstance(result, IRVariable)

    def test_encode_dynarray_dynamic_elements(self):
        """DynArray of dynamic elements (Bytes)."""
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[Bytes[32], 5]) -> DynArray[Bytes[32], 5]:
    return arr
"""
        ctx, node = get_expr_context(source)
        src_ptr = ctx.lookup_ptr("arr")
        typ = DArrayT(BytesT(32), 5)
        max_size = typ.abi_type.size_bound()
        dst_buf = ctx.allocate_buffer(max_size)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, typ, returns_len=True)
        # Nested dynamic encoding
        assert isinstance(result, IRVariable)


class TestABIEncodeNoReturnLen:
    """Test encoding without returns_len (returns None)."""

    def test_encode_no_return_len(self):
        """Encoding without returns_len should return None."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = ctx.lookup_ptr("x")
        dst_buf = ctx.allocate_buffer(32)

        result = abi_encode_to_buf(ctx, dst_buf._ptr, src_ptr, UINT256_T, returns_len=False)
        assert result is None

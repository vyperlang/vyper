"""
Unit tests for ABI decoding in Venom codegen.

Tests the internal abi_decode_to_buf() function that handles
ABI decoding of values from calldata, returndata, and user input.
"""

import pytest

from vyper.codegen_venom.abi import abi_decode_to_buf
from vyper.codegen_venom.abi.abi_decoder import (
    bytes_clamp,
    clamp_basetype,
    int_clamp,
    needs_clamp,
)
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DArrayT,
    DecimalT,
    FlagT,
    IntegerT,
    SArrayT,
    StringT,
    TupleT,
)
from vyper.semantics.types.primitives import IntegerT
from vyper.semantics.types.shortcuts import (
    BYTES32_T,
    INT128_T,
    INT256_T,
    UINT8_T,
    UINT256_T,
)

# Create UINT128_T since it's not in shortcuts
UINT128_T = IntegerT(False, 128)
from vyper.venom.basicblock import IRLiteral, IRVariable

from .builtins.conftest import get_expr_context


class TestNeedsClamp:
    """Test needs_clamp() helper function."""

    def test_uint256_no_clamp(self):
        """uint256 doesn't need clamping (full 256 bits)."""
        assert not needs_clamp(UINT256_T)

    def test_int256_no_clamp(self):
        """int256 doesn't need clamping (full 256 bits)."""
        assert not needs_clamp(INT256_T)

    def test_bytes32_no_clamp(self):
        """bytes32 doesn't need clamping (full 32 bytes)."""
        assert not needs_clamp(BYTES32_T)

    def test_uint8_needs_clamp(self):
        """uint8 needs clamping (sub-256-bit)."""
        assert needs_clamp(UINT8_T)

    def test_uint128_needs_clamp(self):
        """uint128 needs clamping (sub-256-bit)."""
        assert needs_clamp(UINT128_T)

    def test_int128_needs_clamp(self):
        """int128 needs clamping (sub-256-bit, signed)."""
        assert needs_clamp(INT128_T)

    def test_bool_needs_clamp(self):
        """bool needs clamping (only 0 or 1 valid)."""
        assert needs_clamp(BoolT())

    def test_address_needs_clamp(self):
        """address needs clamping (160 bits)."""
        assert needs_clamp(AddressT())

    def test_bytes4_needs_clamp(self):
        """bytes4 needs clamping (left-aligned, low bits must be zero)."""
        assert needs_clamp(BytesM_T(4))

    def test_bytes20_needs_clamp(self):
        """bytes20 needs clamping."""
        assert needs_clamp(BytesM_T(20))

    def test_bytes_dynamic_needs_clamp(self):
        """Bytes dynamic type needs clamping (length validation)."""
        assert needs_clamp(BytesT(100))

    def test_string_needs_clamp(self):
        """String needs clamping (length validation)."""
        assert needs_clamp(StringT(50))

    def test_dynarray_needs_clamp(self):
        """DynArray needs clamping (count validation)."""
        assert needs_clamp(DArrayT(UINT256_T, 10))

    def test_static_array_of_uint256_no_clamp(self):
        """Static array of uint256 doesn't need clamping."""
        assert not needs_clamp(SArrayT(UINT256_T, 5))

    def test_static_array_of_uint8_needs_clamp(self):
        """Static array of uint8 needs clamping (elements need it)."""
        assert needs_clamp(SArrayT(UINT8_T, 5))

    def test_tuple_all_256bit_no_clamp(self):
        """Tuple of uint256/int256 doesn't need clamping."""
        typ = TupleT([UINT256_T, INT256_T])
        assert not needs_clamp(typ)

    def test_tuple_with_subword_needs_clamp(self):
        """Tuple with sub-256-bit member needs clamping."""
        typ = TupleT([UINT256_T, UINT8_T])
        assert needs_clamp(typ)


class TestIntClamp:
    """Test int_clamp() function."""

    def test_unsigned_8bit(self):
        """Test unsigned 8-bit clamping generates proper IR."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = int_clamp(ctx, val, 8, signed=False)
        # Should return the same value (clamping adds assertion but returns val)
        assert result is val

    def test_signed_128bit(self):
        """Test signed 128-bit clamping generates proper IR."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = int_clamp(ctx, val, 128, signed=True)
        assert result is val


class TestBytesClamp:
    """Test bytes_clamp() function."""

    def test_bytes4_clamp(self):
        """Test bytes4 clamping (low 28 bytes must be zero)."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = bytes_clamp(ctx, val, 4)
        assert result is val

    def test_bytes20_clamp(self):
        """Test bytes20 clamping (low 12 bytes must be zero)."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = bytes_clamp(ctx, val, 20)
        assert result is val


class TestClampBasetype:
    """Test clamp_basetype() dispatcher."""

    def test_clamp_uint8(self):
        """Test uint8 clamping dispatches correctly."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = clamp_basetype(ctx, val, UINT8_T)
        assert result is val

    def test_clamp_bool(self):
        """Test bool clamping (only 0 or 1)."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = clamp_basetype(ctx, val, BoolT())
        assert result is val

    def test_clamp_address(self):
        """Test address clamping (160-bit unsigned)."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = clamp_basetype(ctx, val, AddressT())
        assert result is val

    def test_clamp_bytes4(self):
        """Test bytes4 clamping."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        val = ctx.builder.mload(IRLiteral(0))
        result = clamp_basetype(ctx, val, BytesM_T(4))
        assert result is val


class TestABIDecodePrimitive:
    """Test decoding primitive (word) types."""

    def test_decode_uint256(self):
        """Decode uint256 - no clamping needed."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(32)

        # Should not raise
        abi_decode_to_buf(ctx, dst_ptr, src_ptr, UINT256_T)

    def test_decode_uint8(self):
        """Decode uint8 - needs clamping."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(32)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, UINT8_T)

    def test_decode_int128(self):
        """Decode int128 - needs signed clamping."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(32)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, INT128_T)

    def test_decode_bool(self):
        """Decode bool - only 0 or 1 valid."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(32)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, BoolT())

    def test_decode_address(self):
        """Decode address - 160-bit clamping."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(32)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, AddressT())

    def test_decode_bytes4(self):
        """Decode bytes4 - left-aligned, low bits must be zero."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(32)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, BytesM_T(4))


class TestABIDecodeBytestring:
    """Test decoding bytestring types (Bytes, String)."""

    def test_decode_bytes(self):
        """Decode Bytes type."""
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> Bytes[100]:
    return data
"""
        ctx, node = get_expr_context(source)
        typ = BytesT(100)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_string(self):
        """Decode String type."""
        source = """
# @version ^0.4.0
@external
def foo(data: String[50]) -> String[50]:
    return data
"""
        ctx, node = get_expr_context(source)
        typ = StringT(50)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_bytes_with_hi_bound(self):
        """Decode Bytes with buffer bounds checking."""
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> Bytes[100]:
    return data
"""
        ctx, node = get_expr_context(source)
        typ = BytesT(100)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)
        hi = IRLiteral(256)  # Upper bound of buffer

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ, hi=hi)


class TestABIDecodeDynArray:
    """Test decoding dynamic array types."""

    def test_decode_dynarray_static_elements(self):
        """Decode DynArray of static elements."""
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[uint256, 10]) -> DynArray[uint256, 10]:
    return arr
"""
        ctx, node = get_expr_context(source)
        typ = DArrayT(UINT256_T, 10)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_dynarray_needs_clamp_elements(self):
        """Decode DynArray of elements that need clamping."""
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[uint8, 5]) -> DynArray[uint8, 5]:
    return arr
"""
        ctx, node = get_expr_context(source)
        typ = DArrayT(UINT8_T, 5)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_dynarray_dynamic_elements(self):
        """Decode DynArray of dynamic elements (Bytes)."""
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[Bytes[32], 3]) -> DynArray[Bytes[32], 3]:
    return arr
"""
        ctx, node = get_expr_context(source)
        typ = DArrayT(BytesT(32), 3)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_dynarray_with_hi_bound(self):
        """Decode DynArray with buffer bounds checking."""
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[uint256, 10]) -> DynArray[uint256, 10]:
    return arr
"""
        ctx, node = get_expr_context(source)
        typ = DArrayT(UINT256_T, 10)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)
        hi = IRLiteral(512)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ, hi=hi)


class TestABIDecodeComplex:
    """Test decoding complex types (tuples, static arrays)."""

    def test_decode_static_tuple(self):
        """Decode tuple of static types."""
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> (uint256, uint256):
    return (a, b)
"""
        ctx, node = get_expr_context(source)
        typ = TupleT([UINT256_T, UINT256_T])
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_tuple_with_subword(self):
        """Decode tuple containing sub-256-bit types."""
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> (uint256, uint256):
    return (a, b)
"""
        ctx, node = get_expr_context(source)
        typ = TupleT([UINT256_T, UINT8_T, AddressT()])
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_tuple_with_dynamic_member(self):
        """Decode tuple containing dynamic type."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256, data: Bytes[32]) -> (uint256, Bytes[32]):
    return (x, data)
"""
        ctx, node = get_expr_context(source)
        typ = TupleT([UINT256_T, BytesT(32)])
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_static_array(self):
        """Decode static array."""
        source = """
# @version ^0.4.0
@external
def foo(arr: uint256[3]) -> uint256[3]:
    return arr
"""
        ctx, node = get_expr_context(source)
        typ = SArrayT(UINT256_T, 3)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_static_array_of_subword(self):
        """Decode static array of sub-256-bit types."""
        source = """
# @version ^0.4.0
@external
def foo(arr: uint256[3]) -> uint256[3]:
    return arr
"""
        ctx, node = get_expr_context(source)
        typ = SArrayT(UINT8_T, 5)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)


class TestABIDecodeNested:
    """Test decoding nested complex types."""

    def test_decode_array_of_tuples(self):
        """Decode static array of tuples."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        inner_typ = TupleT([UINT256_T, UINT256_T])
        typ = SArrayT(inner_typ, 2)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_dynarray_of_tuples(self):
        """Decode dynamic array of tuples."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        inner_typ = TupleT([UINT256_T, AddressT()])
        typ = DArrayT(inner_typ, 5)
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

    def test_decode_tuple_of_arrays(self):
        """Decode tuple containing arrays."""
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = get_expr_context(source)
        typ = TupleT([SArrayT(UINT256_T, 2), DArrayT(UINT256_T, 3)])
        src_ptr = IRLiteral(0)
        dst_ptr = ctx.allocate_buffer(typ.memory_bytes_required)

        abi_decode_to_buf(ctx, dst_ptr, src_ptr, typ)

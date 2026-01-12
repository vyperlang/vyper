"""
Unit tests for ABI decoding in Venom codegen.

Tests the needs_clamp() function that determines which types need
security-critical clamping during ABI decoding.
"""

import pytest

from vyper.codegen_venom.abi.abi_decoder import needs_clamp
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DArrayT,
    SArrayT,
    StringT,
    TupleT,
)
from vyper.semantics.types.primitives import IntegerT
from vyper.semantics.types.shortcuts import BYTES32_T, INT128_T, INT256_T, UINT8_T, UINT256_T

# Create UINT128_T since it's not in shortcuts
UINT128_T = IntegerT(False, 128)


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

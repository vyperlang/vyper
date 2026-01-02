"""
Tests for storage operations in codegen_venom.

These tests cover:
- load_storage / store_storage for primitive and multi-word types
- load_transient / store_transient (EIP-1153)
- load_immutable / store_immutable
- get_dyn_array_length / set_dyn_array_length (generic, uses Ptr)
"""
import pytest

from vyper.codegen_venom.buffer import Ptr
from vyper.codegen_venom.context import VenomCodegenContext
from vyper.compiler.phases import CompilerData
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.shortcuts import UINT256_T, BYTES32_T, INT256_T
from vyper.semantics.types.bytestrings import BytesT
from vyper.semantics.types.user import StructT
from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _make_context() -> VenomCodegenContext:
    """Create a fresh VenomCodegenContext for testing."""
    source = """
# @version ^0.4.0

@external
def foo():
    pass
"""
    compiler_data = CompilerData(source)
    module_t = compiler_data.global_ctx

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    return VenomCodegenContext(module_t, builder)


class TestLoadStorage:
    """Test load_storage method."""

    def test_load_single_word(self):
        """Loading a single-word type should emit sload."""
        ctx = _make_context()
        slot = IRLiteral(0)

        result = ctx.load_storage(slot, UINT256_T)

        # Should return an IRVariable (result of sload)
        assert isinstance(result, IRVariable)

    def test_load_with_variable_slot(self):
        """Loading from a computed slot should work."""
        ctx = _make_context()
        # Simulate a computed slot
        slot = ctx.builder.add(IRLiteral(1), IRLiteral(2))

        result = ctx.load_storage(slot, UINT256_T)

        assert isinstance(result, IRVariable)

    def test_load_multi_word_type(self):
        """Loading a multi-word type should copy to memory."""
        ctx = _make_context()
        # Create a type that requires 2 storage slots (64 bytes)
        multi_word_typ = BytesT(64)
        slot = IRLiteral(5)

        result = ctx.load_storage(slot, multi_word_typ)

        # Should return a memory pointer (from alloca)
        assert isinstance(result, IRVariable)


class TestStoreStorage:
    """Test store_storage method."""

    def test_store_single_word(self):
        """Storing a single-word type should emit sstore."""
        ctx = _make_context()
        slot = IRLiteral(0)
        val = IRLiteral(42)

        # Should not raise
        ctx.store_storage(val, slot, UINT256_T)

    def test_store_with_variable_slot(self):
        """Storing to a computed slot should work."""
        ctx = _make_context()
        slot = ctx.builder.add(IRLiteral(1), IRLiteral(2))
        val = IRLiteral(100)

        # Should not raise
        ctx.store_storage(val, slot, UINT256_T)

    def test_store_multi_word_type(self):
        """Storing a multi-word type should copy from memory."""
        ctx = _make_context()
        multi_word_typ = BytesT(64)
        slot = IRLiteral(5)
        # Create a memory buffer as source
        buf_val = ctx.new_temporary_value(multi_word_typ)

        # Should not raise
        ctx.store_storage(buf_val.operand, slot, multi_word_typ)


class TestStorageToMemoryCopy:
    """Test multi-word storage operations."""

    def test_load_storage_to_memory_literals(self):
        """Test loading multiple words with literal slot."""
        ctx = _make_context()
        multi_word_typ = BytesT(96)  # 3 words
        slot = IRLiteral(10)
        buf_val = ctx.new_temporary_value(multi_word_typ)

        # Should not raise
        ctx._load_storage_to_memory(slot, buf_val.operand, 3)

    def test_store_memory_to_storage_literals(self):
        """Test storing multiple words with literal slot."""
        ctx = _make_context()
        multi_word_typ = BytesT(96)  # 3 words
        slot = IRLiteral(10)
        buf_val = ctx.new_temporary_value(multi_word_typ)

        # Should not raise
        ctx._store_memory_to_storage(buf_val.operand, slot, 3)

    def test_load_storage_variable_slot(self):
        """Test loading with variable slot (should emit add)."""
        ctx = _make_context()
        # Computed slot
        slot = ctx.builder.add(IRLiteral(5), IRLiteral(10))
        buf_val = ctx.new_temporary_value(BytesT(64))

        # Should not raise
        ctx._load_storage_to_memory(slot, buf_val.operand, 2)


class TestLoadTransient:
    """Test load_transient method."""

    def test_load_single_word(self):
        """Loading a single-word type should emit tload."""
        ctx = _make_context()
        slot = IRLiteral(0)

        result = ctx.load_transient(slot, UINT256_T)

        assert isinstance(result, IRVariable)

    def test_load_multi_word_type(self):
        """Loading a multi-word type should copy to memory."""
        ctx = _make_context()
        multi_word_typ = BytesT(64)
        slot = IRLiteral(5)

        result = ctx.load_transient(slot, multi_word_typ)

        # Should return a memory pointer
        assert isinstance(result, IRVariable)


class TestStoreTransient:
    """Test store_transient method."""

    def test_store_single_word(self):
        """Storing a single-word type should emit tstore."""
        ctx = _make_context()
        slot = IRLiteral(0)
        val = IRLiteral(42)

        # Should not raise
        ctx.store_transient(val, slot, UINT256_T)

    def test_store_multi_word_type(self):
        """Storing a multi-word type should copy from memory."""
        ctx = _make_context()
        multi_word_typ = BytesT(64)
        slot = IRLiteral(5)
        buf_val = ctx.new_temporary_value(multi_word_typ)

        # Should not raise
        ctx.store_transient(buf_val.operand, slot, multi_word_typ)


class TestLoadImmutable:
    """Test load_immutable method."""

    def test_load_single_word(self):
        """Loading a single-word immutable should emit iload."""
        ctx = _make_context()
        offset = IRLiteral(0)

        result = ctx.load_immutable(offset, UINT256_T)

        assert isinstance(result, IRVariable)

    def test_load_multi_word_type(self):
        """Loading a multi-word immutable should copy to memory."""
        ctx = _make_context()
        multi_word_typ = BytesT(64)
        offset = IRLiteral(32)  # Byte offset

        result = ctx.load_immutable(offset, multi_word_typ)

        # Should return a memory pointer
        assert isinstance(result, IRVariable)


class TestStoreImmutable:
    """Test store_immutable method."""

    def test_store_single_word(self):
        """Storing a single-word immutable should emit istore."""
        ctx = _make_context()
        offset = IRLiteral(0)
        val = IRLiteral(42)

        # Should not raise
        ctx.store_immutable(val, offset, UINT256_T)

    def test_store_multi_word_type(self):
        """Storing a multi-word immutable should copy from memory."""
        ctx = _make_context()
        multi_word_typ = BytesT(64)
        offset = IRLiteral(32)
        buf_val = ctx.new_temporary_value(multi_word_typ)

        # Should not raise
        ctx.store_immutable(buf_val.operand, offset, multi_word_typ)


class TestDynArrayLength:
    """Test dynamic array length operations (location-agnostic)."""

    def test_get_dyn_array_length_storage(self):
        """Getting storage dynarray length should emit sload."""
        ctx = _make_context()
        ptr = Ptr(operand=IRLiteral(0), location=DataLocation.STORAGE)

        result = ctx.get_dyn_array_length(ptr)

        assert isinstance(result, IRVariable)

    def test_set_dyn_array_length_storage(self):
        """Setting storage dynarray length should emit sstore."""
        ctx = _make_context()
        ptr = Ptr(operand=IRLiteral(0), location=DataLocation.STORAGE)
        length = IRLiteral(10)

        # Should not raise
        ctx.set_dyn_array_length(ptr, length)

    def test_get_dyn_array_length_memory(self):
        """Getting memory dynarray length should emit mload."""
        ctx = _make_context()
        buf = ctx.allocate_buffer(64)
        ptr = buf.base_ptr()

        result = ctx.get_dyn_array_length(ptr)

        assert isinstance(result, IRVariable)

    def test_set_dyn_array_length_memory(self):
        """Setting memory dynarray length should emit mstore."""
        ctx = _make_context()
        buf = ctx.allocate_buffer(64)
        ptr = buf.base_ptr()
        length = IRLiteral(10)

        # Should not raise
        ctx.set_dyn_array_length(ptr, length)


class TestStorageIntegration:
    """Integration tests for storage operations."""

    def test_store_and_load_roundtrip(self):
        """Test that store/load operations generate IR correctly."""
        ctx = _make_context()
        slot = IRLiteral(5)
        val = IRLiteral(123)

        ctx.store_storage(val, slot, UINT256_T)
        result = ctx.load_storage(slot, UINT256_T)

        assert isinstance(result, IRVariable)

    def test_multi_slot_operations(self):
        """Test operations on consecutive slots."""
        ctx = _make_context()

        # Store to 3 consecutive slots
        for i in range(3):
            ctx.store_storage(IRLiteral(i * 100), IRLiteral(i), UINT256_T)

        # Load from those slots
        for i in range(3):
            result = ctx.load_storage(IRLiteral(i), UINT256_T)
            assert isinstance(result, IRVariable)

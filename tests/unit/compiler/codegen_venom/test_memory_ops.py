"""
Tests for memory operations in codegen_venom.

These tests cover:
- load_memory for primitive and complex types
- store_memory for primitive and complex types
- copy_memory with mcopy vs word-by-word fallback
- load_calldata for primitive and complex types
- allocate_buffer for temporary buffers
"""
import pytest

from vyper.codegen_venom.buffer import Buffer
from vyper.codegen_venom.context import LocalVariable, VenomCodegenContext, VyperValue
from vyper.compiler.phases import CompilerData
from vyper.semantics.types.shortcuts import UINT256_T, BYTES32_T
from vyper.semantics.types.bytestrings import BytesT
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


class TestLoadMemory:
    """Test load_memory method."""

    def test_load_primitive_type(self):
        """Loading a primitive type should emit mload."""
        ctx = _make_context()
        val = ctx.new_temporary_value(UINT256_T)

        result = ctx.load_memory(val.operand, UINT256_T)

        # Should return an IRVariable (result of mload)
        assert isinstance(result, IRVariable)

    def test_load_complex_type_returns_pointer(self):
        """Loading a complex type should return the pointer itself."""
        ctx = _make_context()
        complex_typ = BytesT(100)  # 100-byte string
        val = ctx.new_temporary_value(complex_typ)

        result = ctx.load_memory(val.operand, complex_typ)

        # Should return the same pointer (complex types pass by reference)
        assert result == val.operand


class TestStoreMemory:
    """Test store_memory method."""

    def test_store_primitive_type(self):
        """Storing a primitive type should emit mstore."""
        ctx = _make_context()
        dst = ctx.new_temporary_value(UINT256_T)
        val = IRLiteral(42)

        # Should not raise
        ctx.store_memory(val, dst.operand, UINT256_T)

    def test_store_complex_type_copies_memory(self):
        """Storing a complex type should copy memory."""
        ctx = _make_context()
        complex_typ = BytesT(100)  # 100-byte string
        src_val = ctx.new_temporary_value(complex_typ)
        dst_val = ctx.new_temporary_value(complex_typ)

        # Should not raise (will emit copy instructions)
        ctx.store_memory(src_val.operand, dst_val.operand, complex_typ)


class TestCopyMemory:
    """Test copy_memory method."""

    def test_copy_zero_size(self):
        """Copying zero bytes should be a no-op."""
        ctx = _make_context()
        src = IRLiteral(100)
        dst = IRLiteral(200)

        # Should not raise or emit any instructions
        ctx.copy_memory(dst, src, 0)

    def test_copy_single_word(self):
        """Copying 32 bytes should emit one load/store pair (pre-Cancun)."""
        ctx = _make_context()
        src = IRLiteral(100)
        dst = IRLiteral(200)

        # Should not raise
        ctx.copy_memory(dst, src, 32)

    def test_copy_multiple_words(self):
        """Copying multiple words should emit multiple load/store pairs."""
        ctx = _make_context()
        src = IRLiteral(100)
        dst = IRLiteral(200)

        # Should not raise
        ctx.copy_memory(dst, src, 128)  # 4 words

    def test_copy_with_variable_pointers(self):
        """Copying with variable pointers should use add for offsets."""
        ctx = _make_context()
        src_val = ctx.new_temporary_value(UINT256_T)
        dst_val = ctx.new_temporary_value(UINT256_T)

        # Should not raise
        ctx.copy_memory(dst_val.operand, src_val.operand, 64)  # 2 words


class TestLoadCalldata:
    """Test load_calldata method."""

    def test_load_primitive_from_calldata(self):
        """Loading primitive type should emit calldataload."""
        ctx = _make_context()
        offset = IRLiteral(4)  # After selector

        result = ctx.load_calldata(offset, UINT256_T)

        assert isinstance(result, IRVariable)

    def test_load_complex_from_calldata(self):
        """Loading complex type should copy calldata to memory."""
        ctx = _make_context()
        complex_typ = BytesT(100)
        offset = IRLiteral(4)

        result = ctx.load_calldata(offset, complex_typ)

        # Should return a memory pointer (IRVariable from alloca)
        assert isinstance(result, IRVariable)


class TestAllocateBuffer:
    """Test allocate_buffer method."""

    def test_allocate_small_buffer(self):
        """Should allocate buffer with given size."""
        ctx = _make_context()

        buf = ctx.allocate_buffer(32)

        assert isinstance(buf, Buffer)

    def test_allocate_large_buffer(self):
        """Should allocate larger buffer correctly."""
        ctx = _make_context()

        buf = ctx.allocate_buffer(256)

        assert isinstance(buf, Buffer)

    def test_multiple_allocations(self):
        """Multiple allocations should return different pointers."""
        ctx = _make_context()

        buf1 = ctx.allocate_buffer(32)
        buf2 = ctx.allocate_buffer(32)

        # Different allocations should have different alloca IDs
        assert buf1._ptr != buf2._ptr


class TestNewVariableIntegration:
    """Test new_variable with memory operations."""

    def test_variable_allocation_and_store(self):
        """Test allocating variable and storing to it."""
        ctx = _make_context()

        var = ctx.new_variable("x", UINT256_T)
        assert isinstance(var, LocalVariable)
        ctx.store_memory(IRLiteral(100), var.value.operand, UINT256_T)

        # Should be able to load back
        val = ctx.load_memory(var.value.operand, UINT256_T)
        assert isinstance(val, IRVariable)

    def test_temporary_value_allocation(self):
        """Test allocating temporary value."""
        ctx = _make_context()

        val = ctx.new_temporary_value(UINT256_T)
        assert isinstance(val, VyperValue)
        ctx.store_memory(IRLiteral(42), val.operand, UINT256_T)

        loaded = ctx.load_memory(val.operand, UINT256_T)
        assert isinstance(loaded, IRVariable)

"""
Tests for memory operations in codegen_venom.

Tests pointer handling and zero-size copy optimization.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.compiler.phases import CompilerData
from vyper.semantics.types.bytestrings import BytesT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral
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

    def test_load_complex_type_returns_pointer(self):
        """Loading a complex type should return the pointer itself."""
        ctx = _make_context()
        complex_typ = BytesT(100)  # 100-byte string
        val = ctx.new_temporary_value(complex_typ)

        result = ctx.load_memory(val.operand, complex_typ)

        # Should return the same pointer (complex types pass by reference)
        assert result == val.operand


class TestCopyMemory:
    """Test copy_memory method."""

    def test_copy_zero_size(self):
        """Copying zero bytes should be a no-op."""
        ctx = _make_context()
        src = IRLiteral(100)
        dst = IRLiteral(200)

        # Should not raise or emit any instructions
        ctx.copy_memory(dst, src, 0)

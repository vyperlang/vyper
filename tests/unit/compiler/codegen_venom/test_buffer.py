"""
Unit tests for Buffer and Ptr abstractions.
"""
import pytest

from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.venom.basicblock import IRLiteral, IRVariable

from vyper.codegen_venom.buffer import Buffer, Ptr


class TestBuffer:
    def test_buffer_is_frozen(self):
        """Buffer is immutable (frozen dataclass)."""
        ptr_var = IRVariable("%buf")
        buf = Buffer(_ptr=ptr_var, size=64)

        with pytest.raises(Exception):  # FrozenInstanceError
            buf.size = 128


class TestPtr:
    def test_ptr_memory_without_buf_raises(self):
        """MEMORY Ptr without buf raises CompilerPanic."""
        ptr_var = IRVariable("%ptr")

        with pytest.raises(CompilerPanic, match="buf must be set iff location is MEMORY"):
            Ptr(operand=ptr_var, location=DataLocation.MEMORY, buf=None)

    def test_ptr_storage_with_buf_raises(self):
        """STORAGE Ptr with buf raises CompilerPanic."""
        slot = IRLiteral(0)
        dummy_buf = Buffer(_ptr=IRVariable("%x"), size=32)

        with pytest.raises(CompilerPanic, match="buf must be set iff location is MEMORY"):
            Ptr(operand=slot, location=DataLocation.STORAGE, buf=dummy_buf)

    def test_ptr_is_frozen(self):
        """Ptr is immutable (frozen dataclass)."""
        slot = IRLiteral(0)
        ptr = Ptr(operand=slot, location=DataLocation.STORAGE)

        with pytest.raises(Exception):  # FrozenInstanceError
            ptr.location = DataLocation.MEMORY

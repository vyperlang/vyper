"""
Unit tests for Buffer and Ptr abstractions.
"""
import pytest

from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.venom.basicblock import IRLiteral, IRVariable

from vyper.codegen_venom.buffer import Buffer, Ptr


class TestBuffer:
    def test_buffer_base_ptr_returns_correct_ptr(self):
        """Buffer.base_ptr() returns a Ptr with correct fields."""
        ptr_var = IRVariable("%buf")
        buf = Buffer(_ptr=ptr_var, size=64, annotation="test")

        ptr = buf.base_ptr()

        assert ptr.location == DataLocation.MEMORY
        assert ptr.buf is buf
        assert ptr.operand == ptr_var

    def test_buffer_is_frozen(self):
        """Buffer is immutable (frozen dataclass)."""
        ptr_var = IRVariable("%buf")
        buf = Buffer(_ptr=ptr_var, size=64)

        with pytest.raises(Exception):  # FrozenInstanceError
            buf.size = 128

    def test_buffer_hashable(self):
        """Buffer can be used as dict key (frozen dataclass)."""
        ptr_var = IRVariable("%buf")
        buf = Buffer(_ptr=ptr_var, size=64)

        d = {buf: "test"}
        assert d[buf] == "test"


class TestPtr:
    def test_ptr_memory_requires_buf(self):
        """MEMORY Ptr must have buf set."""
        ptr_var = IRVariable("%ptr")
        buf = Buffer(_ptr=ptr_var, size=64)

        # Valid: MEMORY with buf
        ptr = Ptr(operand=ptr_var, location=DataLocation.MEMORY, buf=buf)
        assert ptr.buf is buf

    def test_ptr_memory_without_buf_raises(self):
        """MEMORY Ptr without buf raises CompilerPanic."""
        ptr_var = IRVariable("%ptr")

        with pytest.raises(CompilerPanic, match="buf must be set iff location is MEMORY"):
            Ptr(operand=ptr_var, location=DataLocation.MEMORY, buf=None)

    def test_ptr_storage_without_buf(self):
        """STORAGE Ptr must not have buf."""
        slot = IRLiteral(0)

        # Valid: STORAGE without buf
        ptr = Ptr(operand=slot, location=DataLocation.STORAGE)
        assert ptr.buf is None

    def test_ptr_storage_with_buf_raises(self):
        """STORAGE Ptr with buf raises CompilerPanic."""
        slot = IRLiteral(0)
        dummy_buf = Buffer(_ptr=IRVariable("%x"), size=32)

        with pytest.raises(CompilerPanic, match="buf must be set iff location is MEMORY"):
            Ptr(operand=slot, location=DataLocation.STORAGE, buf=dummy_buf)

    def test_ptr_transient_without_buf(self):
        """TRANSIENT Ptr must not have buf."""
        slot = IRLiteral(0)

        ptr = Ptr(operand=slot, location=DataLocation.TRANSIENT)
        assert ptr.buf is None

    def test_ptr_calldata_without_buf(self):
        """CALLDATA Ptr must not have buf."""
        offset = IRLiteral(4)

        ptr = Ptr(operand=offset, location=DataLocation.CALLDATA)
        assert ptr.buf is None

    def test_ptr_is_frozen(self):
        """Ptr is immutable (frozen dataclass)."""
        slot = IRLiteral(0)
        ptr = Ptr(operand=slot, location=DataLocation.STORAGE)

        with pytest.raises(Exception):  # FrozenInstanceError
            ptr.location = DataLocation.MEMORY

    def test_ptr_hashable(self):
        """Ptr can be used as dict key (frozen dataclass)."""
        slot = IRLiteral(0)
        ptr = Ptr(operand=slot, location=DataLocation.STORAGE)

        d = {ptr: "test"}
        assert d[ptr] == "test"

"""
Buffer and Ptr abstractions for Venom codegen memory management.

Buffer: An allocated memory region (from alloca instruction).
Ptr: A pointer to a location (memory, storage, calldata, transient).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.venom.basicblock import IROperand, IRVariable


@dataclass(frozen=True)
class Buffer:
    """
    An allocated memory region.

    Use buf.base_ptr() to get a Ptr to the start.
    Buffers are always MEMORY (from alloca instruction).
    """

    _ptr: IRVariable  # The alloca result (private)
    size: int  # Allocation size in bytes
    annotation: Optional[str] = None  # Debug annotation

    def base_ptr(self) -> Ptr:
        """Get a Ptr to the start of this buffer."""
        return Ptr(operand=self._ptr, location=DataLocation.MEMORY, buf=self)


@dataclass(frozen=True)
class Ptr:
    """
    A pointer to a location (memory, storage, calldata, transient).

    location is required - a Ptr always points somewhere.

    Invariant: buf is set iff location is MEMORY. Every memory pointer
    tracks its buffer provenance. Non-memory pointers never have buf.
    """

    operand: IROperand  # The pointer value in IR
    location: DataLocation  # Required, never None
    buf: Optional[Buffer] = None  # Provenance (MEMORY only)

    def __post_init__(self):
        if (self.buf is not None) != (self.location == DataLocation.MEMORY):
            raise CompilerPanic("Ptr: buf must be set iff location is MEMORY")

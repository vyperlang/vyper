"""
VenomValue: Location-aware wrapper for IR operands.

Solves the pointer/value confusion in codegen by carrying location info
alongside the operand. Use ctx.unwrap(vv) to load the value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from vyper.semantics.data_locations import DataLocation
from vyper.venom.basicblock import IROperand

if TYPE_CHECKING:
    from vyper.semantics.types.base import VyperType


@dataclass
class VenomValue:
    """Location-aware wrapper for IR operands.

    - operand: The IR value (literal or variable)
    - location: Where the data lives (STORAGE, MEMORY, etc.), or None if already a value
    - typ: The Vyper type, needed to know if it's a primitive word or complex type

    For values already loaded or computed, location=None.
    For pointers/slots, location indicates where to load from.

    Use ctx.unwrap(vv) to get the loaded value.
    """

    operand: IROperand
    location: Optional[DataLocation] = None
    typ: Optional["VyperType"] = None

    @staticmethod
    def val(operand: IROperand) -> "VenomValue":
        """Create a VenomValue for an already-loaded value."""
        return VenomValue(operand, None, None)

    @staticmethod
    def loc(operand: IROperand, location: DataLocation, typ: "VyperType") -> "VenomValue":
        """Create a VenomValue for a pointer/slot that needs loading."""
        return VenomValue(operand, location, typ)

    @property
    def is_location(self) -> bool:
        """True if this represents a pointer/slot, not a loaded value."""
        return self.location is not None

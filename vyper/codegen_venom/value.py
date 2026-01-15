"""
VyperValue: Location-aware wrapper for IR operands.

Solves the pointer/value confusion in codegen by carrying location info
alongside the operand. Use ctx.unwrap(vv) to load the value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from vyper.codegen_venom.buffer import Ptr
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.venom.basicblock import IROperand

if TYPE_CHECKING:
    from vyper.semantics.types.base import VyperType


@dataclass(frozen=True)
class VyperValue:
    """
    A value in Vyper-land: either on the EVM stack or at a storage location.

    This is an explicit tagged union:
    - Stack value: _operand is set, _ptr is None
    - Located value: _ptr is set, _operand is None

    Use factory methods to construct.
    """

    typ: "VyperType"
    _operand: Optional[IROperand] = None
    _ptr: Optional[Ptr] = None

    def __post_init__(self):
        if (self._operand is None) == (self._ptr is None):
            raise CompilerPanic("VyperValue: exactly one of _operand or _ptr must be set")

    @property
    def is_stack_value(self) -> bool:
        return self._ptr is None

    def ptr(self) -> Ptr:
        if self._ptr is None:
            raise CompilerPanic("cannot get ptr from stack value")
        return self._ptr

    def stack_value(self) -> IROperand:
        if self._ptr is not None:
            raise CompilerPanic("cannot get stack_value from located value")
        assert self._operand is not None
        return self._operand

    @property
    def operand(self) -> IROperand:
        if self._operand is not None:
            return self._operand
        assert self._ptr is not None
        return self._ptr.operand

    @property
    def location(self) -> Optional[DataLocation]:
        return self._ptr.location if self._ptr else None

    @classmethod
    def from_stack_op(cls, operand: IROperand, typ: "VyperType") -> "VyperValue":
        return cls(typ=typ, _operand=operand)

    @classmethod
    def from_ptr(cls, ptr: Ptr, typ: "VyperType") -> "VyperValue":
        return cls(typ=typ, _ptr=ptr)

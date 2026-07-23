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
        if (self._operand is None) == (self._ptr is None):  # pragma: nocover
            raise CompilerPanic("VyperValue: exactly one of _operand or _ptr must be set")

    @property
    def is_stack_value(self) -> bool:
        return self._ptr is None

    def ptr(self) -> Ptr:
        if self._ptr is None:  # pragma: nocover
            raise CompilerPanic("cannot get ptr from stack value")
        return self._ptr

    def stack_value(self) -> IROperand:
        if self._ptr is not None:  # pragma: nocover
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


@dataclass(frozen=True)
class PreparedValue:
    """A fully prepared runtime value.

    Unlike :class:`VyperValue`, which may denote a value at any data
    location, a ``PreparedValue`` is ready for emission-free consumption:

    - primitive words are already loaded into an IR operand;
    - composite values are backed by stable memory.

    Accessing either representation never emits IR.  Call-boundary lowering
    can therefore prepare arguments in source order and hand them to a
    consumer without allowing a later load or materialization to reorder the
    observable evaluation.
    """

    typ: "VyperType"
    _word: Optional[IROperand] = None
    _memory: Optional[Ptr] = None

    def __post_init__(self):
        if (self._word is None) == (self._memory is None):  # pragma: nocover
            raise CompilerPanic("PreparedValue: exactly one representation must be set")

        if self._word is not None and not self.typ._is_prim_word:  # pragma: nocover
            raise CompilerPanic("PreparedValue: only primitive words may use word form")

        if self._memory is not None:
            if self.typ._is_prim_word:  # pragma: nocover
                raise CompilerPanic("PreparedValue: primitive words must be loaded eagerly")
            if self._memory.location is not DataLocation.MEMORY:  # pragma: nocover
                raise CompilerPanic("PreparedValue: composite values must be in memory")

    @property
    def is_word(self) -> bool:
        return self._word is not None

    @property
    def operand(self) -> IROperand:
        if self._word is not None:
            return self._word
        assert self._memory is not None
        return self._memory.operand

    def word(self) -> IROperand:
        if self._word is None:  # pragma: nocover
            raise CompilerPanic("cannot get word from prepared memory value")
        return self._word

    def ptr(self) -> Ptr:
        if self._memory is None:  # pragma: nocover
            raise CompilerPanic("cannot get ptr from prepared word value")
        return self._memory

    @classmethod
    def from_word(cls, operand: IROperand, typ: "VyperType") -> "PreparedValue":
        return cls(typ=typ, _word=operand)

    @classmethod
    def from_memory(cls, ptr: Ptr, typ: "VyperType") -> "PreparedValue":
        return cls(typ=typ, _memory=ptr)

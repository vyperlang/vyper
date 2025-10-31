from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass
from typing import ClassVar

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRAbstractMemLoc, IRLiteral, IROperand, IRVariable


class MemoryLocation:
    # Initialize after class definition
    EMPTY: ClassVar[MemoryLocation]
    UNDEFINED: ClassVar[MemoryLocation]

    @classmethod
    def from_operands(
            cls, offset: IROperand | int, size: IROperand | int, translates: dict, /, is_volatile: bool = False
    ) -> MemoryLocation:
        if isinstance(size, IRLiteral):
            _size = size.value
        elif isinstance(size, IRVariable):
            _size = None
        elif isinstance(size, int):
            _size = size
        else:  # pragma: nocover
            raise CompilerPanic(f"invalid size: {size} ({type(size)})")

        _offset: int | IRAbstractMemLoc | None = None
        if isinstance(offset, IRLiteral):
            _offset = offset.value
            return MemoryLocationConcrete(_offset, _size)
        elif isinstance(offset, IRVariable):
            _offset = None
            op = translates.get(offset, None)
            if op is None:
                return MemoryLocationConcrete(_offset=None, _size=_size)
            else:
                return MemoryLocationAbstract(op=op, _offset=None, _size=_size)
        elif isinstance(offset, int):
            _offset = offset
            return MemoryLocationConcrete(_offset, _size)
        elif isinstance(offset, IRAbstractMemLoc):
            op = offset
            return MemoryLocationAbstract(op=op, _offset=op.offset, _size=_size)
        else:  # pragma: nocover
            raise CompilerPanic(f"invalid offset: {offset} ({type(offset)})")


    @property
    def offset(self) -> int | None:
        raise NotImplementedError

    @property
    def size(self) -> int | None:
        raise NotImplementedError

    @property
    def is_offset_fixed(self) -> bool:
        raise NotImplementedError

    @property
    def is_size_fixed(self) -> bool:
        raise NotImplementedError

    @property
    def is_fixed(self) -> bool:
        raise NotImplementedError

    @property
    def is_volatile(self) -> bool:
        raise NotImplementedError

    @staticmethod
    def may_overlap(loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        if loc1.size == 0 or loc2.size == 0:
            return False
        if not loc1.is_offset_fixed or not loc2.is_offset_fixed:
            return True
        if loc1 is MemoryLocation.UNDEFINED or loc2 is MemoryLocation.UNDEFINED:
            return True
        if type(loc1) is not type(loc2):
            return False
        if isinstance(loc1, MemoryLocationConcrete):
            assert isinstance(loc2, MemoryLocationConcrete)
            return MemoryLocationConcrete.may_overlap_concrete(loc1, loc2)
        if isinstance(loc1, MemoryLocationAbstract):
            assert isinstance(loc2, MemoryLocationAbstract)
            return MemoryLocationAbstract.may_overlap_abstract(loc1, loc2)
        return False

    def completely_contains(self, other: MemoryLocation) -> bool:
        raise NotImplementedError

    def create_volatile(self) -> MemoryLocation:
        raise NotImplementedError


@dataclass(frozen=True)
class MemoryLocationAbstract(MemoryLocation):
    op: IRAbstractMemLoc
    _offset: int | None
    _size: int | None
    _is_volatile: bool = False

    @property
    def offset(self):
        raise NotImplementedError

    @property
    def size(self):
        return self._size

    @property
    def is_offset_fixed(self) -> bool:
        return True

    @property
    def is_size_fixed(self) -> bool:
        return True

    @property
    def is_fixed(self) -> bool:
        return True

    @property
    def is_volatile(self) -> bool:
        return self._is_volatile

    def create_volatile(self) -> MemoryLocationAbstract:
        return dc.replace(self, _is_volatile=True)

    @staticmethod
    def may_overlap_abstract(loc1: MemoryLocationAbstract, loc2: MemoryLocationAbstract) -> bool:
        if loc1.op._id == loc2.op._id:
            conc1 = MemoryLocationConcrete(_offset=loc1._offset, _size=loc1.size)
            conc2 = MemoryLocationConcrete(_offset=loc2._offset, _size=loc2.size)
            return MemoryLocationConcrete.may_overlap_concrete(conc1, conc2)
        else:
            return False

    def completely_contains(self, other: MemoryLocation) -> bool:
        if other == MemoryLocation.UNDEFINED:
            return False
        if not isinstance(other, MemoryLocationAbstract):
            return False
        if self._size is None:
            return False
        if other.size == 0:
            return True
        if self.op._id == other.op._id:
            conc1 = MemoryLocationConcrete(_offset=self._offset, _size=self.size)
            conc2 = MemoryLocationConcrete(_offset=other._offset, _size=other.size)
            return conc1.completely_contains(conc2)
        return False


@dataclass(frozen=True)
class MemoryLocationConcrete(MemoryLocation):
    """Represents a memory location that can be analyzed for aliasing"""

    _offset: int | None = None
    _size: int | None = None
    _is_volatile: bool = False
    # Locations that should be considered volatile. Example usages of this would
    # be locations that are accessed outside of the current function.

    @property
    def offset(self):
        return self._offset

    @property
    def size(self):
        return self._size

    @property
    def is_offset_fixed(self) -> bool:
        return self.offset is not None

    @property
    def is_size_fixed(self) -> bool:
        return self.size is not None

    @property
    def is_fixed(self) -> bool:
        return self.is_offset_fixed and self.is_size_fixed

    @property
    def is_volatile(self) -> bool:
        return self._is_volatile

    def create_volatile(self) -> MemoryLocationConcrete:
        return dc.replace(self, _is_volatile=True)

    # similar code to memmerging._Interval, but different data structure
    def completely_contains(self, other: MemoryLocation) -> bool:
        # If other is empty (size 0), always contained
        if other.size == 0:
            return True

        # If self has unknown offset or size, can't guarantee containment
        if not self.is_offset_fixed or not self.is_size_fixed:
            return False

        # If other has unknown offset or size, can't guarantee containment
        if not other.is_offset_fixed or not other.is_size_fixed:
            return False

        if not isinstance(other, MemoryLocationConcrete):
            return False

        # Both are known
        assert self.offset is not None and self.size is not None
        assert other.offset is not None and other.size is not None
        start1, end1 = self.offset, self.offset + self.size
        start2, end2 = other.offset, other.offset + other.size

        return start1 <= start2 and end1 >= end2

    def get_size_lit(self) -> IRLiteral:
        assert self._size is not None
        return IRLiteral(self._size)

    def get_offset_lit(self, offset=0) -> IRLiteral:
        assert self._offset is not None
        return IRLiteral(self._offset + offset)

    @staticmethod
    def may_overlap_concrete(loc1: MemoryLocationConcrete, loc2: MemoryLocationConcrete) -> bool:
        """
        Determine if two memory locations may overlap
        """
        o1, s1 = loc1.offset, loc1.size
        o2, s2 = loc2.offset, loc2.size

        # If either size is zero, no alias
        if s1 == 0 or s2 == 0:
            return False

        if o1 is None or o2 is None:
            # If offsets are unknown, can't be sure
            return True

        # guaranteed now that o1 and o2 are not None

        # All known
        if s1 is not None and s2 is not None:
            end1 = o1 + s1
            end2 = o2 + s2
            return not (end1 <= o2 or end2 <= o1)

        # loc1 known size, loc2 unknown size
        if s1 is not None:
            # end of loc1 is bounded by start of loc2
            if o1 + s1 <= o2:
                return False
            # Otherwise, can't be sure
            return True

        # loc2 known size, loc1 unknown size
        if s2 is not None:
            # end of loc2 is bounded by start of loc1
            if o2 + s2 <= o1:
                return False

            # Otherwise, can't be sure
            return True

        return True


MemoryLocation.EMPTY = MemoryLocationConcrete(_offset=0, _size=0)
MemoryLocation.UNDEFINED = MemoryLocationConcrete(_offset=None, _size=None)


def get_write_location(inst, addr_space: AddrSpace, translates: dict) -> MemoryLocation:
    """Extract memory location info from an instruction"""
    if addr_space == MEMORY:
        return _get_memory_write_location(inst, translates)
    elif addr_space in (STORAGE, TRANSIENT):
        return _get_storage_write_location(inst, addr_space, translates)
    else:  # pragma: nocover
        raise CompilerPanic(f"Invalid location type: {addr_space}")


def get_read_location(inst, addr_space: AddrSpace, translates) -> MemoryLocation:
    """Extract memory location info from an instruction"""
    if addr_space == MEMORY:
        return _get_memory_read_location(inst, translates)
    elif addr_space in (STORAGE, TRANSIENT):
        return _get_storage_read_location(inst, addr_space, translates)
    else:  # pragma: nocover
        raise CompilerPanic(f"Invalid location type: {addr_space}")


def _get_memory_write_location(inst, translates: dict) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return MemoryLocation.from_operands(dst, MEMORY.word_scale, translates)
    elif opcode == "mload":
        return MemoryLocation.EMPTY
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        size, _, dst = inst.operands
        return MemoryLocation.from_operands(dst, size, translates)
    elif opcode == "dload":
        return MemoryLocationConcrete(_offset=0, _size=32)
    elif opcode == "sha3_64":
        return MemoryLocationConcrete(_offset=0, _size=64)
    elif opcode == "invoke":
        return MemoryLocation.UNDEFINED
    elif opcode == "call":
        size, dst, _, _, _, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size, translates)
    elif opcode in ("delegatecall", "staticcall"):
        size, dst, _, _, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size, translates)
    elif opcode == "extcodecopy":
        size, _, dst, _ = inst.operands
        return MemoryLocation.from_operands(dst, size, translates)

    return MemoryLocationConcrete.EMPTY


def _get_memory_read_location(inst, translates) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == "mstore":
        return MemoryLocationConcrete.EMPTY
    elif opcode == "mload":
        return MemoryLocation.from_operands(inst.operands[0], MEMORY.word_scale, translates)
    elif opcode == "mcopy":
        size, src, _ = inst.operands
        return MemoryLocation.from_operands(src, size, translates)
    elif opcode == "dload":
        return MemoryLocationConcrete(_offset=0, _size=32)
    elif opcode == "invoke":
        return MemoryLocation.UNDEFINED
    elif opcode == "call":
        _, _, size, dst, _, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size, translates)
    elif opcode in ("delegatecall", "staticcall"):
        _, _, size, dst, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size, translates)
    elif opcode == "return":
        size, src = inst.operands
        return MemoryLocation.from_operands(src, size, translates)
    elif opcode == "create":
        size, src, _value = inst.operands
        return MemoryLocation.from_operands(src, size, translates)
    elif opcode == "create2":
        _salt, size, src, _value = inst.operands
        return MemoryLocation.from_operands(src, size, translates)
    elif opcode == "sha3":
        size, offset = inst.operands
        return MemoryLocation.from_operands(offset, size, translates)
    elif opcode == "sha3_64":
        return MemoryLocationConcrete(_offset=0, _size=64)
    elif opcode == "log":
        size, src = inst.operands[-2:]
        return MemoryLocation.from_operands(src, size, translates)
    elif opcode == "revert":
        size, src = inst.operands
        return MemoryLocation.from_operands(src, size, translates)

    return MemoryLocationConcrete.EMPTY


def _get_storage_write_location(inst, addr_space: AddrSpace, translates) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == addr_space.store_op:
        dst = inst.operands[1]
        return MemoryLocation.from_operands(dst, addr_space.word_scale, translates)
    elif opcode == addr_space.load_op:
        return MemoryLocation.EMPTY
    elif opcode in ("call", "delegatecall", "staticcall"):
        return MemoryLocation.UNDEFINED
    elif opcode == "invoke":
        return MemoryLocation.UNDEFINED
    elif opcode in ("create", "create2"):
        return MemoryLocation.UNDEFINED

    return MemoryLocation.EMPTY


def _get_storage_read_location(inst, addr_space: AddrSpace, translates) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == addr_space.store_op:
        return MemoryLocation.EMPTY
    elif opcode == addr_space.load_op:
        return MemoryLocation.from_operands(inst.operands[0], addr_space.word_scale, translates)
    elif opcode in ("call", "delegatecall", "staticcall"):
        return MemoryLocation.UNDEFINED
    elif opcode == "invoke":
        return MemoryLocation.UNDEFINED
    elif opcode in ("create", "create2"):
        return MemoryLocation.UNDEFINED
    elif opcode in ("return", "stop", "sink"):
        # these opcodes terminate execution and commit to (persistent)
        # storage, resulting in storage writes escaping our control.
        # returning `MemoryLocation.UNDEFINED` represents "future" reads
        # which could happen in the next program invocation.
        # while not a "true" read, this case makes the code in DSE simpler.
        return MemoryLocation.UNDEFINED
    elif opcode == "ret":
        # `ret` escapes our control and returns execution to the
        # caller function. to be conservative, we model these as
        # "future" reads which could happen in the caller.
        # while not a "true" read, this case makes the code in DSE simpler.
        return MemoryLocation.UNDEFINED

    return MemoryLocation.EMPTY

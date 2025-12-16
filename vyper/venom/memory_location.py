from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass
from typing import ClassVar, Optional

from vyper.utils import MemoryPositions
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand
from vyper.venom.function import IRFunction


class MemoryLocation:
    # Initialize after class definition
    EMPTY: ClassVar[MemoryLocation]
    UNDEFINED: ClassVar[MemoryLocation]

    def is_empty(self) -> bool:  # pragma: nocover
        raise NotImplementedError

    @property
    def is_offset_fixed(self) -> bool:  # pragma: nocover
        raise NotImplementedError

    @property
    def is_size_fixed(self) -> bool:  # pragma: nocover
        raise NotImplementedError

    @property
    def is_fixed(self) -> bool:  # pragma: nocover
        raise NotImplementedError

    @property
    def is_volatile(self) -> bool:  # pragma: nocover
        raise NotImplementedError

    @staticmethod
    def may_overlap(loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        if loc1.is_empty() or loc2.is_empty():
            return False
        if loc1 is MemoryLocation.UNDEFINED or loc2 is MemoryLocation.UNDEFINED:
            return True
        if type(loc1) is not type(loc2):
            return False
        if isinstance(loc1, MemoryLocationSegment):
            assert isinstance(loc2, MemoryLocationSegment)
            return MemoryLocationSegment.may_overlap_concrete(loc1, loc2)
        if isinstance(loc1, MemoryLocationAbstract):
            assert isinstance(loc2, MemoryLocationAbstract)
            return MemoryLocationAbstract.may_overlap_abstract(loc1, loc2)
        return False

    def completely_contains(self, other: MemoryLocation) -> bool:  # pragma: nocover
        raise NotImplementedError

    def mk_volatile(self) -> MemoryLocation:  # pragma: nocover
        raise NotImplementedError

    def offset_by(self, offset: Optional[int]) -> MemoryLocation:
        raise NotImplementedError


@dataclass(frozen=True)
class MemoryLocationAbstract(MemoryLocation):
    source: IRInstruction
    maximum_size: int
    segment: MemoryLocationSegment

    def is_empty(self):
        return self.segment.is_empty()

    @property
    def is_offset_fixed(self) -> bool:
        return self.segment.is_offset_fixed

    @property
    def is_size_fixed(self) -> bool:
        return self.segment.is_size_fixed

    @property
    def is_fixed(self) -> bool:
        return self.segment.is_fixed

    @property
    def is_volatile(self) -> bool:
        return self.segment.is_volatile

    def mk_volatile(self) -> MemoryLocationAbstract:
        return dc.replace(self, segment=self.segment.mk_volatile())

    @staticmethod
    def may_overlap_abstract(loc1: MemoryLocationAbstract, loc2: MemoryLocationAbstract) -> bool:
        if loc1.source is loc2.source:
            return MemoryLocationSegment.may_overlap_concrete(loc1.segment, loc2.segment)
        else:
            return False

    def completely_contains(self, other: MemoryLocation) -> bool:
        if other == MemoryLocation.UNDEFINED:
            return False
        if not isinstance(other, MemoryLocationAbstract):
            return False
        if self.maximum_size is None:
            return False
        if other.is_empty():
            return True
        if self.source is other.source:
            return self.segment.completely_contains(other.segment)
        return False

    def offset_by(self, offset: Optional[int]) -> MemoryLocation:
        return dc.replace(self, segment=self.segment.offset_by(offset))


@dataclass(frozen=True)
class MemoryLocationSegment(MemoryLocation):
    """Represents a memory location that can be analyzed for aliasing"""

    offset: Optional[int] = None
    size: Optional[int] = None
    _is_volatile: bool = False
    # Locations that should be considered volatile. Example usages of this would
    # be locations that are accessed outside of the current function.

    def is_empty(self):
        return self.size == 0

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

    def mk_volatile(self) -> MemoryLocationSegment:
        return dc.replace(self, _is_volatile=True)

    # similar code to memmerging._Interval, but different data structure
    def completely_contains(self, other: MemoryLocation) -> bool:
        # If other is empty (size 0), always contained
        if other.is_empty():
            return True

        # If self has unknown offset or size, can't guarantee containment
        if not self.is_offset_fixed or not self.is_size_fixed:
            return False

        # If other has unknown offset or size, can't guarantee containment
        if not other.is_offset_fixed or not other.is_size_fixed:
            return False

        if not isinstance(other, MemoryLocationSegment):
            return False

        # Both are known
        assert self.offset is not None and self.size is not None
        assert other.offset is not None and other.size is not None
        start1, end1 = self.offset, self.offset + self.size
        start2, end2 = other.offset, other.offset + other.size

        return start1 <= start2 and end1 >= end2

    @staticmethod
    def may_overlap_concrete(loc1: MemoryLocationSegment, loc2: MemoryLocationSegment) -> bool:
        """
        Determine if two memory locations may overlap
        """
        if not loc1.is_offset_fixed or not loc2.is_offset_fixed:
            return True

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

    def offset_by(self, offset: Optional[int]) -> MemoryLocation:
        if offset is None:
            return dc.replace(self, offset=None)

        if self.offset is None:
            return dc.replace(self, offset=None)

        return dc.replace(self, offset=self.offset + offset)


MemoryLocation.EMPTY = MemoryLocationSegment(offset=0, size=0)
MemoryLocation.UNDEFINED = MemoryLocationSegment(offset=None, size=None)




def in_free_var(var, offset):
    return offset >= var and offset < (var + 32)


def fix_mem_loc(function: IRFunction):
    return
    for bb in function.get_basic_blocks():
        for inst in bb.instructions:
            write_op = get_memory_write_op(inst)
            read_op = get_memory_read_op(inst)
            if write_op is not None:
                size = get_write_size(inst)
                if size is None or not isinstance(write_op.value, int):
                    continue

                if in_free_var(MemoryPositions.FREE_VAR_SPACE, write_op.value):
                    print(inst.parent)
                    offset = write_op.value - MemoryPositions.FREE_VAR_SPACE
                    _update_write_location(inst, IRAbstractMemLoc.FREE_VAR1.with_offset(offset))
                elif in_free_var(MemoryPositions.FREE_VAR_SPACE2, write_op.value):
                    offset = write_op.value - MemoryPositions.FREE_VAR_SPACE2
                    _update_write_location(inst, IRAbstractMemLoc.FREE_VAR2.with_offset(offset))
            if read_op is not None:
                size = _get_read_size(inst)
                if size is None or not isinstance(read_op.value, int):
                    continue

                if in_free_var(MemoryPositions.FREE_VAR_SPACE, read_op.value):
                    offset = read_op.value - MemoryPositions.FREE_VAR_SPACE
                    _update_read_location(inst, IRAbstractMemLoc.FREE_VAR1.with_offset(offset))
                elif in_free_var(MemoryPositions.FREE_VAR_SPACE2, read_op.value):
                    offset = read_op.value - MemoryPositions.FREE_VAR_SPACE2
                    _update_read_location(inst, IRAbstractMemLoc.FREE_VAR2.with_offset(offset))


def get_memory_write_op(inst) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return dst
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        _, _, dst = inst.operands
        return dst
    elif opcode == "call":
        _, dst, _, _, _, _, _ = inst.operands
        return dst
    elif opcode in ("delegatecall", "staticcall"):
        _, dst, _, _, _, _ = inst.operands
        return dst
    elif opcode == "extcodecopy":
        _, _, dst, _ = inst.operands
        return dst

    return None


def get_write_size(inst: IRInstruction) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mstore":
        return IRLiteral(32)
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        size, _, _ = inst.operands
        return size
    elif opcode == "call":
        size, _, _, _, _, _, _ = inst.operands
        return size
    elif opcode in ("delegatecall", "staticcall"):
        size, _, _, _, _, _ = inst.operands
        return size
    elif opcode == "extcodecopy":
        size, _, _, _ = inst.operands
        return size

    return None


def get_memory_read_op(inst) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mload":
        return inst.operands[0]
    elif opcode == "mcopy":
        _, src, _ = inst.operands
        return src
    elif opcode == "call":
        _, _, _, src, _, _, _ = inst.operands
        return src
    elif opcode in ("delegatecall", "staticcall"):
        _, _, _, src, _, _ = inst.operands
        return src
    elif opcode == "return":
        _, src = inst.operands
        return src
    elif opcode == "create":
        _, src, _ = inst.operands
        return src
    elif opcode == "create2":
        _, size, src, _ = inst.operands
        return src
    elif opcode == "sha3":
        _, offset = inst.operands
        return offset
    elif opcode == "log":
        _, src = inst.operands[-2:]
        return src
    elif opcode == "revert":
        size, src = inst.operands
        if size.value == 0:
            return None
        return src

    return None


def _get_read_size(inst: IRInstruction) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mload":
        return IRLiteral(32)
    elif opcode == "mcopy":
        size, _, _ = inst.operands
        return size
    elif opcode == "call":
        _, _, size, _, _, _, _ = inst.operands
        return size
    elif opcode in ("delegatecall", "staticcall"):
        _, _, size, _, _, _ = inst.operands
        return size
    elif opcode == "return":
        size, _ = inst.operands
        return size
    elif opcode == "create":
        size, _, _ = inst.operands
        return size
    elif opcode == "create2":
        _, size, _, _ = inst.operands
        return size
    elif opcode == "sha3":
        size, _ = inst.operands
        return size
    elif opcode == "log":
        size, _ = inst.operands[-2:]
        return size
    elif opcode == "revert":
        size, _ = inst.operands
        if size.value == 0:
            return None
        return size

    return None


def _update_write_location(inst, new_op: IROperand):
    opcode = inst.opcode
    if opcode == "mstore":
        inst.operands[1] = new_op
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        inst.operands[2] = new_op
    elif opcode == "call":
        inst.operands[1] = new_op
    elif opcode in ("delegatecall", "staticcall"):
        inst.operands[1] = new_op
    elif opcode == "extcodecopy":
        inst.operands[2] = new_op


def _update_read_location(inst, new_op: IROperand):
    opcode = inst.opcode
    if opcode == "mload":
        inst.operands[0] = new_op
    elif opcode == "mcopy":
        inst.operands[1] = new_op
    elif opcode == "call":
        inst.operands[3] = new_op
    elif opcode in ("delegatecall", "staticcall", "call"):
        inst.operands[3] = new_op
    elif opcode == "return":
        inst.operands[1] = new_op
    elif opcode == "create":
        inst.operands[1] = new_op
    elif opcode == "create2":
        inst.operands[2] = new_op
    elif opcode == "sha3":
        inst.operands[1] = new_op
    elif opcode == "log":
        inst.operands[-1] = new_op
    elif opcode == "revert":
        inst.operands[1] = new_op

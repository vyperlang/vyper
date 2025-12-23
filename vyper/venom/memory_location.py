from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar, Optional

from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand


# abstract / interface
# TODO: rename to MemorySegment
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
            return True
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


@dataclass(frozen=True)
class MemoryLocationAbstract(MemoryLocation):
    source: IRInstruction  # *alloca instruction
    segment: MemoryLocationSegment

    def __post_init__(self):
        assert self.source.opcode in ("alloca", "palloca"), self.source

        # if we have segment.is_fixed, we can statically check for oob access
        if self.segment.is_fixed:
            if self.segment.offset + self.segment.size > self.source_size:
                # the memory access is oob! (outside of the allocated region)
                raise CompilerPanic(f"oob memory access, {self}")

    # REVIEW: unused?
    @cached_property
    def source_size(self) -> int:
        size = self.source.operands[0]
        assert isinstance(size, IRLiteral)
        return size.value

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
        if other.is_empty():
            return True
        if self.source is other.source:
            return self.segment.completely_contains(other.segment)
        return False


MemoryLocation.EMPTY = MemoryLocationSegment(offset=0, size=0)
MemoryLocation.UNDEFINED = MemoryLocationSegment(offset=None, size=None)


@dataclass
# TODO: come up with better name
# TODO: maybe this should go in somewhere higher level?
#   e.g. directly in basicblock.py or analysis/.
class InstAccessOps:
    ofst: Optional[IROperand]
    size: Optional[IROperand]
    max_size: Optional[IROperand] = None

    def __post_init__(self):
        if self.max_size is None:
            self.max_size = self.size


# REVIEW: rename to get_memory_write_ofst
# or shorter: get_write_ofst, get_mem_write_ofst
def memory_write_ops(inst) -> InstAccessOps:
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return InstAccessOps(ofst=dst, size=IRLiteral(32))
    if opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        size, _, dst = inst.operands
        return InstAccessOps(ofst=dst, size=size)
    if opcode == "call":
        max_size, dst, _, _, _, _, _ = inst.operands
        # number of bytes written is indeterminate -- could
        # write anywhere between 0 and output_buffer_size bytes.
        return InstAccessOps(ofst=dst, size=None, max_size=max_size)
    if opcode in ("delegatecall", "staticcall"):
        max_size, dst, _, _, _, _ = inst.operands
        # ditto
        return InstAccessOps(ofst=dst, size=None, max_size=max_size)
    if opcode == "extcodecopy":
        size, _, dst, _ = inst.operands
        return InstAccessOps(ofst=dst, size=size)

    return InstAccessOps(ofst=None, size=None)


# REVIEW: rename (mem_write_ofst? get_mem_write_ofst?)
def get_memory_write_op(inst: IRInstruction) -> Optional[IROperand]:
    return memory_write_ops(inst).ofst


# REVIEW: rename (mem_write_size? get_mem_write_size?)
def get_write_size(inst: IRInstruction) -> Optional[IROperand]:
    return memory_write_ops(inst).size


def get_write_max_size(inst: IRInstruction) -> Optional[IROperand]:
    return memory_write_ops(inst).max_size


def memory_read_ops(inst) -> InstAccessOps:
    opcode = inst.opcode
    if opcode == "mload":
        ofst = inst.operands[0]
        size = IRLiteral(32)
        return InstAccessOps(ofst=ofst, size=size)

    if opcode == "mcopy":
        size, src, _ = inst.operands
        return InstAccessOps(ofst=src, size=size)

    if opcode == "call":
        _, _, size, src, _, _, _ = inst.operands
        return InstAccessOps(ofst=src, size=size)
    if opcode in ("delegatecall", "staticcall"):
        _, _, size, src, _, _ = inst.operands
        return InstAccessOps(ofst=src, size=size)
    if opcode == "return":
        size, src = inst.operands
        return InstAccessOps(ofst=src, size=size)
    if opcode == "create":
        size, _, _ = inst.operands
        size, src, _ = inst.operands
        return InstAccessOps(ofst=src, size=size)

    if opcode == "create2":
        _, size, src, _ = inst.operands
        return InstAccessOps(ofst=src, size=size)

    elif opcode == "sha3":
        size, ofst = inst.operands
        return InstAccessOps(ofst=ofst, size=size)
    elif opcode == "log":
        size, src = inst.operands[-2:]
        return InstAccessOps(ofst=src, size=size)
    elif opcode == "revert":
        size, src = inst.operands
        return InstAccessOps(ofst=src, size=size)

    return InstAccessOps(ofst=None, size=None)


# REVIEW: get_mem_read_ofst
def get_memory_read_op(inst) -> Optional[IROperand]:
    return memory_read_ops(inst).ofst


def get_read_size(inst: IRInstruction) -> Optional[IROperand]:
    return memory_read_ops(inst).size


def update_write_location(inst, new_op: IROperand):
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

    else:  # pragma: nocover
        raise CompilerPanic("unreachable")


def update_read_location(inst, new_op: IROperand):
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

    else:  # pragma: nocover
        raise CompilerPanic("unreachable")

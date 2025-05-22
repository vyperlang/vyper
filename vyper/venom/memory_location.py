from __future__ import annotations

from dataclasses import dataclass

from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable


@dataclass(frozen=True)
class MemoryLocation:
    """Represents a memory location that can be analyzed for aliasing"""

    offset: int | None = None
    size: int | None = None
    # Locations that should be considered volatile. Example usages of this would
    # be locations that are accessed outside of the current function.
    is_volatile: bool = False

    @property
    def is_offset_fixed(self) -> bool:
        return self.offset is not None

    @property
    def is_size_fixed(self) -> bool:
        return self.size is not None

    @property
    def is_fixed(self) -> bool:
        return self.is_offset_fixed and self.is_size_fixed

    @classmethod
    def from_operands(
        cls, offset: IROperand | int, size: IROperand | int, /, is_volatile: bool = False
    ) -> MemoryLocation:
        if isinstance(offset, IRLiteral):
            _offset = offset.value
        elif isinstance(offset, IRVariable):
            _offset = None
        elif isinstance(offset, int):
            _offset = offset
        else:
            raise CompilerPanic(f"invalid offset: {offset} ({type(offset)})")

        if isinstance(size, IRLiteral):
            _size = size.value
        elif isinstance(size, IRVariable):
            _size = None
        elif isinstance(size, int):
            _size = size
        else:
            raise CompilerPanic(f"invalid size: {size} ({type(size)})")

        return cls(_offset, _size, is_volatile)

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

        # Both are known
        assert self.offset is not None and self.size is not None
        assert other.offset is not None and other.size is not None
        start1, end1 = self.offset, self.offset + self.size
        start2, end2 = other.offset, other.offset + other.size

        return start1 <= start2 and end1 >= end2

    @staticmethod
    def may_overlap(loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        """
        Determine if two memory locations may overlap
        """
        if loc1 == EMPTY_MEMORY_ACCESS or loc2 == EMPTY_MEMORY_ACCESS:
            return False

        o1, s1 = loc1.offset, loc1.size
        o2, s2 = loc2.offset, loc2.size

        # If either size is zero, no alias
        if s1 == 0 or s2 == 0:
            return False

        # All known
        if loc1.is_fixed and loc2.is_fixed:
            end1 = o1 + s1  # type: ignore
            end2 = o2 + s2  # type: ignore
            return not (end1 <= o2 or end2 <= o1)  # type: ignore

        # If both offsets are known
        if loc1.is_offset_fixed and loc2.is_offset_fixed:
            # loc1 known size, loc2 unknown size
            if loc1.is_size_fixed and not loc2.is_size_fixed:
                if o1 + s1 <= o2:  # type: ignore
                    return False
            # loc2 known size, loc1 unknown size
            if loc2.is_size_fixed and not loc1.is_size_fixed:
                if o2 + s2 <= o1:  # type: ignore
                    return False

            # Otherwise, can't be sure
            return True

        # If offsets are unknown, can't be sure
        return True


EMPTY_MEMORY_ACCESS = MemoryLocation(offset=0, size=0, is_volatile=False)


def get_write_memory_location(inst) -> MemoryLocation:
    """Extract memory location info from an instruction"""
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return MemoryLocation.from_operands(dst, 32)
    elif opcode == "mload":
        return EMPTY_MEMORY_ACCESS
    elif opcode == "mcopy":
        size, _, dst = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode == "calldatacopy":
        size, _, dst = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode == "dloadbytes":
        size, _, dst = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode == "dload":
        return MemoryLocation(offset=0, size=32)
    elif opcode == "sha3_64":
        return MemoryLocation(offset=0, size=64)
    elif opcode == "invoke":
        return MemoryLocation(offset=0, size=None)
    elif opcode == "call":
        size, dst, _, _, _, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode in ("delegatecall", "staticcall"):
        size, dst, _, _, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode in ("codecopy", "extcodecopy"):
        size, _, dst = inst.operands[:3]
        return MemoryLocation.from_operands(dst, size)
    elif opcode == "returndatacopy":
        size, _, dst = inst.operands
        return MemoryLocation.from_operands(dst, size)
    return EMPTY_MEMORY_ACCESS


def get_read_memory_location(inst) -> MemoryLocation:
    """Extract memory location info from an instruction"""
    opcode = inst.opcode
    if opcode == "mstore":
        return EMPTY_MEMORY_ACCESS
    elif opcode == "mload":
        return MemoryLocation.from_operands(inst.operands[0], 32)
    elif opcode == "mcopy":
        size, src, _ = inst.operands
        return MemoryLocation.from_operands(src, size)
    elif opcode == "calldatacopy":
        return EMPTY_MEMORY_ACCESS
    elif opcode == "dloadbytes":
        return EMPTY_MEMORY_ACCESS
    elif opcode == "dload":
        return MemoryLocation(offset=0, size=32)
    elif opcode == "invoke":
        return MemoryLocation(offset=0, size=None)
    elif opcode == "call":
        _, _, size, dst, _, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode in ("delegatecall", "staticcall"):
        _, _, size, dst, _, _ = inst.operands
        return MemoryLocation.from_operands(dst, size)
    elif opcode == "return":
        size, src = inst.operands
        return MemoryLocation.from_operands(src, size)
    elif opcode == "create":
        size, src, _value = inst.operands
        return MemoryLocation.from_operands(src, size)
    elif opcode == "create2":
        _salt, size, src, _value = inst.operands
        return MemoryLocation.from_operands(src, size)
    elif opcode == "sha3":
        size, offset = inst.operands
        return MemoryLocation.from_operands(offset, size)
    elif opcode == "sha3_32":
        raise CompilerPanic("invalid opcode")  # should be unused
    elif opcode == "sha3_64":
        return MemoryLocation(offset=0, size=64)
    elif opcode == "log":
        size, src = inst.operands[-2:]
        return MemoryLocation.from_operands(src, size)
    elif opcode == "revert":
        size, src = inst.operands
        return MemoryLocation.from_operands(src, size)
    return EMPTY_MEMORY_ACCESS

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
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

    # Initialize after class definition
    EMPTY: ClassVar[MemoryLocation]
    UNDEFINED: ClassVar[MemoryLocation]

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
        else:  # pragma: nocover
            raise CompilerPanic(f"invalid offset: {offset} ({type(offset)})")

        if isinstance(size, IRLiteral):
            _size = size.value
        elif isinstance(size, IRVariable):
            _size = None
        elif isinstance(size, int):
            _size = size
        else:  # pragma: nocover
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


MemoryLocation.EMPTY = MemoryLocation(offset=0, size=0)
MemoryLocation.UNDEFINED = MemoryLocation(offset=None, size=None)


def get_write_location(inst, addr_space: AddrSpace) -> MemoryLocation:
    """Extract memory location info from an instruction"""
    if addr_space == MEMORY:
        return _get_memory_write_location(inst)
    elif addr_space in (STORAGE, TRANSIENT):
        return _get_storage_write_location(inst, addr_space)
    else:  # pragma: nocover
        raise CompilerPanic(f"Invalid location type: {addr_space}")


def get_read_location(inst, addr_space: AddrSpace) -> MemoryLocation:
    """Extract memory location info from an instruction"""
    if addr_space == MEMORY:
        return _get_memory_read_location(inst)
    elif addr_space in (STORAGE, TRANSIENT):
        return _get_storage_read_location(inst, addr_space)
    else:  # pragma: nocover
        raise CompilerPanic(f"Invalid location type: {addr_space}")


def _get_memory_write_location(inst) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return MemoryLocation.from_operands(dst, MEMORY.word_scale)
    elif opcode == "mload":
        return MemoryLocation.EMPTY
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
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
    elif opcode == "extcodecopy":
        size, _, dst, _ = inst.operands
        return MemoryLocation.from_operands(dst, size)

    return MemoryLocation.EMPTY


def _get_memory_read_location(inst) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == "mstore":
        return MemoryLocation.EMPTY
    elif opcode == "mload":
        return MemoryLocation.from_operands(inst.operands[0], MEMORY.word_scale)
    elif opcode == "mcopy":
        size, src, _ = inst.operands
        return MemoryLocation.from_operands(src, size)
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
    elif opcode == "sha3_64":
        return MemoryLocation(offset=0, size=64)
    elif opcode == "log":
        size, src = inst.operands[-2:]
        return MemoryLocation.from_operands(src, size)
    elif opcode == "revert":
        size, src = inst.operands
        return MemoryLocation.from_operands(src, size)

    return MemoryLocation.EMPTY


def _get_storage_write_location(inst, addr_space: AddrSpace) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == addr_space.store_op:
        dst = inst.operands[1]
        return MemoryLocation.from_operands(dst, addr_space.word_scale)
    elif opcode == addr_space.load_op:
        return MemoryLocation.EMPTY
    elif opcode in ("call", "delegatecall", "staticcall"):
        return MemoryLocation.UNDEFINED
    elif opcode == "invoke":
        return MemoryLocation.UNDEFINED
    elif opcode in ("create", "create2"):
        return MemoryLocation.UNDEFINED

    return MemoryLocation.EMPTY


def _get_storage_read_location(inst, addr_space: AddrSpace) -> MemoryLocation:
    opcode = inst.opcode
    if opcode == addr_space.store_op:
        return MemoryLocation.EMPTY
    elif opcode == addr_space.load_op:
        return MemoryLocation.from_operands(inst.operands[0], addr_space.word_scale)
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

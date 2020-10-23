from typing import List

from vyper.exceptions import CompilerPanic
from vyper.utils import MemoryPositions


class FreeMemory:
    __slots__ = ("position", "size")

    def __init__(self, position: int, size: int) -> None:
        self.position = position
        self.size = size

    def __repr__(self):
        return f"(FreeMemory: pos={self.position}, size={self.size})"

    def partially_allocate(self, size: int) -> int:
        """
        Reduce the size of the free memory by allocating from the initial offset.

        Arguments
        ---------
        size : int
            Number of bytes to allocate

        Returns
        -------
        int
            Position of the newly allocated memory
        """
        if size >= self.size:
            raise CompilerPanic("Attempted to allocate more memory than available")
        position = self.position
        self.position += size
        self.size -= size
        return position


class MemoryAllocator:
    """
    Low-level memory alloctor. Used to allocate and de-allocate memory slots.

    This object should not be accessed directly. Memory allocation happens via
    declaring variables within `Context`.
    """

    next_mem: int

    def __init__(self, start_position: int = MemoryPositions.RESERVED_MEMORY):
        """
        Initializer.

        Arguments
        ---------
        start_position : int, optional
            The initial offset to use as the free memory pointer. Offsets
            prior to this value are considered permanently allocated.
        """
        self.next_mem = start_position
        self.size_of_mem = start_position
        self.deallocated_mem: List[FreeMemory] = []

    # Get the next unused memory location
    def get_next_memory_position(self) -> int:
        return self.next_mem

    def allocate_memory(self, size: int) -> int:
        """
        Allocate `size` bytes in memory.

        *** No guarantees are made that allocated memory is clean! ***

        If no memory was previously de-allocated, memory is expanded
        and the free memory pointer is increased.

        If sufficient space is available within de-allocated memory, the lowest
        available offset is returned and that memory is now marked as allocated.

        Arguments
        ---------
        size : int
            The number of bytes to allocate. Must be divisible by 32.

        Returns
        -------
        int
            Start offset of the newly allocated memory.
        """
        if size % 32 != 0:
            raise CompilerPanic("Memory misaligment, only multiples of 32 supported.")

        # check for deallocated memory prior to expanding
        for i, free_memory in enumerate(self.deallocated_mem):
            if free_memory.size == size:
                del self.deallocated_mem[i]
                return free_memory.position
            if free_memory.size > size:
                return free_memory.partially_allocate(size)

        # if no deallocated slots are available, expand memory
        return self.expand_memory(size)

    def expand_memory(self, size: int) -> int:
        """
        Allocate `size` bytes in memory, starting from the free memory pointer.
        """
        if size % 32 != 0:
            raise CompilerPanic("Memory misaligment, only multiples of 32 supported.")

        before_value = self.next_mem
        self.next_mem += size
        self.size_of_mem = max(self.size_of_mem, self.next_mem)
        return before_value

    def deallocate_memory(self, pos: int, size: int) -> None:
        """
        De-allocate memory.

        Arguments
        ---------
        pos : int
            The initial memory position to de-allocate.
        size : int
            The number of bytes to de-allocate. Must be divisible by 32.
        """
        if size % 32 != 0:
            raise CompilerPanic("Memory misaligment, only multiples of 32 supported.")

        self.deallocated_mem.append(FreeMemory(position=pos, size=size))
        self.deallocated_mem.sort(key=lambda k: k.position)

        if not self.deallocated_mem:
            return

        # iterate over deallocated memory and merge slots where possible
        i = 1
        active = self.deallocated_mem[0]
        while len(self.deallocated_mem) > i:
            next_slot = self.deallocated_mem[i]
            if next_slot.position == active.position + active.size:
                active.size += next_slot.size
                self.deallocated_mem.remove(next_slot)
            else:
                active = next_slot
                i += 1

        # if the highest free memory slot ends at the edge of the
        # allocated memory, reduce the free memory pointer
        last = self.deallocated_mem[-1]
        if last.position + last.size == self.next_mem:
            self.next_mem = last.position
            del self.deallocated_mem[-1]

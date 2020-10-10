from typing import List

from vyper.exceptions import CompilerPanic
from vyper.utils import MemoryPositions


class FreeMemory:
    __slots__ = (
        "position",
        "size",
    )

    def __init__(self, position, size):
        self.position = position
        self.size = size

    def __repr__(self):
        return f"(FreeMemory: pos={self.position}, size={self.size})"


class MemoryAllocator:
    next_mem: int

    def __init__(self, start_position: int = MemoryPositions.RESERVED_MEMORY):
        self.next_mem = start_position
        self.released_mem: List[FreeMemory] = []

    # Get the next unused memory location
    def get_next_memory_position(self) -> int:
        return self.next_mem

    # Grow memory by x bytes
    def increase_memory(self, size: int) -> int:
        if size % 32 != 0:
            raise CompilerPanic("Memory misaligment, only multiples of 32 supported.")

        # check for released memory prior to expanding
        for i, free_memory in enumerate(self.released_mem):
            if free_memory.size == size:
                del self.released_mem[i]
                return free_memory.position
            if free_memory.size > size:
                position = free_memory.position
                free_memory.position += size
                free_memory.size -= size
                return position

        # if no released slots are avaialble, expand memory
        before_value = self.next_mem
        self.next_mem += size
        return before_value

    def release_memory(self, pos: int, size: int) -> None:
        if size % 32 != 0:
            raise CompilerPanic("Memory misaligment, only multiples of 32 supported.")

        # releasing from the end of the allocated memory - reduce the free memory pointer
        if pos + size == self.next_mem:
            self.next_mem = pos
            return

        if not self.released_mem or self.released_mem[-1].position < pos:
            # no previously released memory, or this is the highest position released
            self.released_mem.append(FreeMemory(position=pos, size=size))
        else:
            # previously released memory exists with a higher offset
            idx = self.released_mem.index(next(i for i in self.released_mem if i.position > pos))
            self.released_mem.insert(idx, FreeMemory(position=pos, size=size))

        # iterate over released memory and merge slots where possible
        i = 1
        active = self.released_mem[0]
        while len(self.released_mem) > i:
            next_slot = self.released_mem[i]
            if next_slot.position == active.position + active.size:
                active.size += next_slot.size
                self.released_mem.remove(next_slot)
            else:
                active = next_slot
                i += 1

from typing import Tuple

from vyper.exceptions import CompilerPanic
from vyper.utils import MemoryPositions


class MemoryAllocator:
    next_mem: int

    def __init__(self, start_position: int = MemoryPositions.RESERVED_MEMORY):
        self.next_mem = start_position

    # Get the next unused memory location
    def get_next_memory_position(self) -> int:
        return self.next_mem

    # Grow memory by x bytes
    def increase_memory(self, size: int) -> Tuple[int, int]:
        if size % 32 != 0:
            raise CompilerPanic("Memory misaligment, only multiples of 32 supported.")
        before_value = self.next_mem
        self.next_mem += size
        return before_value, self.next_mem

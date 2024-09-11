from typing import List


class MemoryBlock:
    size: int
    address: int
    is_free: bool

    def __init__(self, size: int, address: int):
        self.size = size
        self.address = address
        self.is_free = True


class MemoryAllocator:
    total_size: int
    start_address: int
    blocks: List[MemoryBlock]

    def __init__(self, total_size: int, start_address: int):
        self.total_size = total_size
        self.start_address = start_address
        self.blocks = [MemoryBlock(total_size, 0)]

    def allocate(self, size: int) -> int:
        for block in self.blocks:
            if block.is_free and block.size >= size:
                if block.size > size:
                    new_block = MemoryBlock(block.size - size, block.address + size)
                    self.blocks.insert(self.blocks.index(block) + 1, new_block)
                    block.size = size
                block.is_free = False
                return self.start_address + block.address
        raise MemoryError("Memory allocation failed")

    def deallocate(self, address: int) -> bool:
        relative_address = address - self.start_address
        for block in self.blocks:
            if block.address == relative_address:
                block.is_free = True
                self._merge_adjacent_free_blocks()
                return True
        return False  # invalid address

    def _merge_adjacent_free_blocks(self) -> None:
        i = 0
        while i < len(self.blocks) - 1:
            if self.blocks[i].is_free and self.blocks[i + 1].is_free:
                self.blocks[i].size += self.blocks[i + 1].size
                self.blocks.pop(i + 1)
            else:
                i += 1

    def get_free_memory(self) -> int:
        return sum(block.size for block in self.blocks if block.is_free)

    def get_allocated_memory(self) -> int:
        return sum(block.size for block in self.blocks if not block.is_free)

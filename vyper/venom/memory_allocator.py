from vyper.venom.memory_location import MemoryLocation
from vyper.venom.basicblock import IRLiteral

class MemoryAllocator:
    curr: int
    def __init__(self):
        self.curr = 0

    def allocate(self, size: int | IRLiteral) -> MemoryLocation:
        if isinstance(size, IRLiteral):
            size = size.value
        res = MemoryLocation(self.curr, size)
        self.curr += size
        return res

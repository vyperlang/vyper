from vyper.venom.basicblock import IRAbstractMemLoc, IRLiteral
from vyper.venom.memory_location import MemoryLocation


class MemoryAllocator:
    allocated: dict[IRAbstractMemLoc, MemoryLocation]
    curr: int

    def __init__(self):
        self.curr = 0
        self.allocated = dict()

    def allocate(self, size: int | IRLiteral) -> MemoryLocation:
        if isinstance(size, IRLiteral):
            size = size.value
        res = MemoryLocation(self.curr, size)
        self.curr += size
        return res

    def get_place(self, mem_loc: IRAbstractMemLoc) -> MemoryLocation:
        if mem_loc in self.allocated:
            return self.allocated[mem_loc]
        res = self.allocate(mem_loc.size)
        self.allocated[mem_loc] = res
        return res

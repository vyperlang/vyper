from vyper.venom.basicblock import IRAbstractMemLoc, IRLiteral
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.function import IRFunction


class MemoryAllocator:
    allocated: dict[IRAbstractMemLoc, MemoryLocation]
    curr: int
    function_mem_used: dict[IRFunction, int]

    def __init__(self):
        self.curr = 0
        self.allocated = dict()
        self.function_mem_used = dict()

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

    def start_fn_allocation(self, callsites_used: int):
        self.before = self.curr
        self.curr = callsites_used
    
    def end_fn_allocation(self, fn: IRFunction):
        self.function_mem_used[fn] = self.curr
        self.curr = self.before


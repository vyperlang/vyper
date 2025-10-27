from vyper.venom.function import IRFunction
from vyper.venom.memory_location import MemoryLocationConcrete, IRAbstractMemLoc, IRLiteral


class MemoryAllocator:
    allocated: dict[int, MemoryLocationConcrete]
    curr: int
    function_mem_used: dict[IRFunction, int]

    def __init__(self):
        self.curr = 0
        self.allocated = dict()
        self.function_mem_used = dict()

    def allocate(self, size: int | IRLiteral) -> MemoryLocationConcrete:
        if isinstance(size, IRLiteral):
            size = size.value
        res = MemoryLocationConcrete(self.curr, size)
        self.curr += size
        return res

    def get_place(self, mem_loc: IRAbstractMemLoc) -> MemoryLocationConcrete:
        if mem_loc._id in self.allocated:
            return self.allocated[mem_loc._id]
        res = self.allocate(mem_loc.size)
        self.allocated[mem_loc._id] = res
        return res

    def start_fn_allocation(self, callsites_used: int):
        self.before = self.curr
        self.curr = callsites_used

    def end_fn_allocation(self, fn: IRFunction):
        self.function_mem_used[fn] = self.curr
        self.curr = self.before

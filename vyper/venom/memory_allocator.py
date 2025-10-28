from typing import Any

from vyper.venom.basicblock import IRAbstractMemLoc, IRLiteral


class MemoryAllocator:
    allocated: dict[int, tuple[int, int]]
    curr: int
    function_mem_used: dict[Any, int]

    def __init__(self):
        self.curr = 0
        self.allocated = dict()
        self.function_mem_used = dict()

    def allocate(self, size: int | IRLiteral) -> tuple[int, int]:
        if isinstance(size, IRLiteral):
            size = size.value
        res = self.curr
        self.curr += size
        return res, size

    def get_place(self, mem_loc: IRAbstractMemLoc) -> int:
        if mem_loc._id in self.allocated:
            return self.allocated[mem_loc._id][0]
        res = self.allocate(mem_loc.size)
        self.allocated[mem_loc._id] = res
        return res[0]

    def start_fn_allocation(self, callsites_used: int):
        self.before = self.curr
        self.curr = callsites_used

    def end_fn_allocation(self, fn):
        self.function_mem_used[fn] = self.curr
        self.curr = self.before

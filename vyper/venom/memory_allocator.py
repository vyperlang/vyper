from typing import Any, ClassVar

from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRAbstractMemLoc


class MemoryAllocator:
    allocated: dict[int, tuple[int, int]]
    curr: int
    mems_used: dict[Any, OrderedSet[IRAbstractMemLoc]]
    allocated_fn: OrderedSet[IRAbstractMemLoc]
    FN_START: ClassVar[int] = 64

    def __init__(self):
        self.curr = 0
        self.allocated = dict()
        self.mems_used = dict()
        self.allocated_fn = OrderedSet()

    def allocate(self, mem_loc: IRAbstractMemLoc) -> int:
        ptr = self.curr
        self.curr += mem_loc.size
        assert mem_loc._id not in self.allocated
        self.allocated[mem_loc._id] = (ptr, mem_loc.size)
        self.allocated_fn.add(mem_loc)
        return ptr

    def start_fn_allocation(self):
        self.curr = MemoryAllocator.FN_START
        self.allocated_fn = OrderedSet()

    def already_allocated(self, mems: list[IRAbstractMemLoc]):
        self.allocated_fn.addmany(mems)

    def end_fn_allocation(self, fn):
        self.mems_used[fn] = OrderedSet(self.allocated_fn)

    def reset(self):
        self.curr = MemoryAllocator.FN_START
    
    def reserve(self, mem_loc: IRAbstractMemLoc):
        assert mem_loc._id in self.allocated
        ptr, size = self.allocated[mem_loc._id]
        self.curr = max(ptr + size, self.curr)

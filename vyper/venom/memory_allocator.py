from typing import Any

from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRAbstractMemLoc


class MemoryAllocator:
    allocated: dict[int, tuple[int, int]]
    curr: int
    mems_used: dict[Any, OrderedSet[IRAbstractMemLoc]]

    def __init__(self):
        self.curr = 0
        self.allocated = dict()
        self.mems_used = dict()

    def allocate(self, mem_loc: IRAbstractMemLoc) -> int:
        ptr = self.curr
        self.curr += mem_loc.size
        assert mem_loc._id not in self.allocated
        self.allocated[mem_loc._id] = (ptr, mem_loc.size)
        return ptr

    def start_fn_allocation(self):
        # REVIEW: more flexible to set the start pos in the ctor
        # (e.g. self.start_ptr = 64)
        # or even as a class variable (MemoryAllocator.START_POS)
        self.curr = 64

    def end_fn_allocation(self, mems: list[IRAbstractMemLoc], fn):
        self.mems_used[fn] = OrderedSet(mems)

    def reset(self):
        self.curr = 64
    
    def reserve(self, mem_loc: IRAbstractMemLoc):
        assert mem_loc._id in self.allocated
        ptr, size = self.allocated[mem_loc._id]
        self.curr = max(ptr + size, self.curr)

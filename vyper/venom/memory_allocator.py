from typing import Any

from vyper.venom.basicblock import IRAbstractMemLoc, IRLiteral
from vyper.utils import OrderedSet


class MemoryAllocator:
    allocated: dict[int, tuple[int, int]]
    curr: int
    mems_used: dict[Any, OrderedSet[IRAbstractMemLoc]]

    def __init__(self):
        self.curr = 0
        self.allocated = dict()
        self.mems_used = dict()

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

    def start_fn_allocation(self):
        self.curr = 64

    def end_fn_allocation(self, mems: list[IRAbstractMemLoc], fn):
        self.mems_used[fn] = OrderedSet(mems)

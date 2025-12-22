from typing import ClassVar

from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRAbstractMemLoc
from vyper.venom.function import IRFunction


class MemoryAllocator:
    # global state:
    #   all allocated mems, mem_id => (ptr, size)
    allocated: dict[int, tuple[int, int]]
    #   function => set of memlocs in that function
    # (free vars + union of all mems_used is equivalent to `allocated`)
    mems_used: dict[IRFunction, OrderedSet[IRAbstractMemLoc]]
    #   function => end of memory for that function
    fn_eom: dict[IRFunction, int]

    # mems allocated in current function
    allocated_fn: OrderedSet[IRAbstractMemLoc]
    # current function
    current_fn: IRFunction
    # current end of memory
    eom: int

    FN_START: ClassVar[int] = 64

    def __init__(self):
        # start from 0 so we can allocate FREE_VAR_SPACE in slots 0 and 32
        self.eom = 0

        self.allocated = dict()
        self.mems_used = dict()
        self.fn_eom = dict()
        self.allocated_fn = OrderedSet()

    def allocate(self, mem_loc: IRAbstractMemLoc) -> int:
        ptr = self.eom
        self.eom += mem_loc.size
        assert mem_loc._id not in self.allocated
        self.allocated[mem_loc._id] = (ptr, mem_loc.size)
        self.allocated_fn.add(mem_loc)
        return ptr

    def start_fn_allocation(self, fn):
        self.current_function = fn
        self.eom = MemoryAllocator.FN_START
        self.allocated_fn = OrderedSet()

    def add_allocated(self, mems: list[IRAbstractMemLoc]):
        self.allocated_fn.addmany(mems)

    def end_fn_allocation(self):
        self.mems_used[self.current_function] = OrderedSet(self.allocated_fn)
        self.fn_eom[self.current_function] = self.eom

    def reset(self):
        self.eom = MemoryAllocator.FN_START

    def reserve(self, mem_loc: IRAbstractMemLoc):
        assert mem_loc._id in self.allocated
        ptr, size = self.allocated[mem_loc._id]
        self.eom = max(ptr + size, self.eom)

from typing import ClassVar

from vyper.utils import OrderedSet
from vyper.venom.analysis.base_ptr_analysis import Ptr
from vyper.venom.basicblock import IRLiteral
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import Allocation


class MemoryAllocator:
    global_allocation: set[tuple[int, int]]
    # global state:
    #   all allocated mems, alloca => (ptr, size)
    allocated: dict[Allocation, int]
    #   function => set of memlocs in that function
    # (free vars + union of all mems_used is equivalent to `allocated`)
    mems_used: dict[IRFunction, OrderedSet[Allocation]]

    #   function => end of memory for that function
    fn_eom: dict[IRFunction, int]

    # mems allocated in current function (allocas/pallocas)
    allocated_fn: OrderedSet[Allocation]
    # current function
    current_function: IRFunction

    # reserved positions: set[tuple[position, size]]
    reserved: set[tuple[int, int]]

    FN_START: ClassVar[int] = 0

    def __init__(self):
        self.reserved = set()

        self.global_allocation = set()
        self.allocated = dict()
        self.mems_used = dict()
        self.fn_eom = dict()
        self.allocated_fn = OrderedSet()

    def set_position(self, alloca: Allocation, position: int):
        self.allocated[alloca] = position

    def add_global(self, alloca: Allocation):
        assert alloca in self.allocated
        ptr = self.allocated[alloca]
        self.global_allocation.add((ptr, alloca.alloca_size))

    def allocate(self, alloca: Allocation) -> int:
        assert alloca not in self.allocated

        reserved = sorted(list(self.reserved))

        ptr = MemoryAllocator.FN_START
        size = alloca.alloca_size

        for resv_ptr, resv_size in reserved:
            resv_end = resv_ptr + resv_size
            if resv_end <= ptr:
                continue

            # found the place
            if resv_ptr >= ptr + size:
                break

            ptr = resv_end

        self.allocated[alloca] = ptr
        self.allocated_fn.add(alloca)
        return ptr

    def is_allocated(self, alloca: Allocation) -> bool:
        return alloca in self.allocated

    def get_concrete(self, ptr: Ptr) -> IRLiteral:
        assert self.is_allocated(ptr.base_alloca)
        assert ptr.offset is not None
        return IRLiteral(self.allocated[ptr.base_alloca] + ptr.offset)

    def start_fn_allocation(self, fn):
        self.reserved = self.global_allocation.copy()
        self.current_function = fn
        self.allocated_fn = OrderedSet()

    def add_allocated(self, mems: list[Allocation]):
        self.allocated_fn.addmany(mems)

    def end_fn_allocation(self):
        # defensive copy
        self.mems_used[self.current_function] = self.allocated_fn.copy()

        self.fn_eom[self.current_function] = self.compute_fn_eom()

    def compute_fn_eom(self) -> int:
        eom = 0
        for ptr, size in self.global_allocation:
            eom = max(eom, ptr + size)
        for alloca in self.allocated_fn:
            offset = self.allocated[alloca]
            eom = max(eom, offset + alloca.alloca_size)
        return eom

    def reset(self):
        self.reserved = self.global_allocation.copy()

    def reserve(self, alloca: Allocation):
        assert alloca in self.allocated
        ptr = self.allocated[alloca]
        self.reserved.add((ptr, alloca.alloca_size))

    def reserve_all(self):
        for mem in self.allocated_fn:
            self.reserve(mem)

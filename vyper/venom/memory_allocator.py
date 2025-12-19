from typing import ClassVar

from vyper.utils import OrderedSet
from vyper.venom.analysis.base_ptr_analysis import BasePtr
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.function import IRFunction


class MemoryAllocator:
    # global state:
    #   all allocated mems, alloca => (ptr, size)
    allocated: dict[IRInstruction, tuple[int, int]]
    #   function => set of memlocs in that function
    # (free vars + union of all mems_used is equivalent to `allocated`)
    mems_used: dict[IRFunction, OrderedSet[IRInstruction]]

    # mems allocated in current function (allocas/pallocas)
    allocated_fn: OrderedSet[BasePtr]
    # current function
    current_fn: IRFunction
    # current end of memory
    eom: int

    reseved: set[tuple[int, int]]

    FN_START: ClassVar[int] = 0

    def __init__(self):
        self.eom = 0
        self.reserved = set()

        self.allocated = dict()
        self.mems_used = dict()
        self.allocated_fn = OrderedSet()

    def set_position(self, base_ptr: BasePtr, position: int):
        assert base_ptr.source.opcode in ("alloca", "palloca")
        self.allocated[base_ptr.source] = (position, base_ptr.size)

    def allocate(self, base_ptr: BasePtr | IRInstruction) -> int:
        if isinstance(base_ptr, IRInstruction):
            base_ptr = BasePtr.from_alloca(base_ptr)
        assert isinstance(base_ptr, BasePtr)
        ptr = self.eom
        self.eom += base_ptr.size
        assert base_ptr.source not in self.allocated

        reserved = sorted(list(self.reserved))

        ptr = MemoryAllocator.FN_START
        size = base_ptr.size

        for resv_ptr, resv_size in reserved:
            # can happen if this allocation
            # ovelaps with allocations that dont
            # ovelap each other
            if resv_ptr < ptr:
                ptr = resv_ptr + resv_size
                continue

            # found the place
            if resv_ptr >= ptr + size:
                break

            ptr = resv_ptr + resv_size

        self.allocated[base_ptr.source] = (ptr, size)
        self.allocated_fn.add(base_ptr)
        return ptr

    def is_allocated(self, alloc: BasePtr | IRInstruction) -> bool:
        if isinstance(alloc, BasePtr):
            return alloc.source in self.allocated
        else:
            assert alloc.opcode in ("alloca", "palloca"), alloc
            return alloc in self.allocated

    def get_concrete(self, base_ptr: BasePtr) -> IRLiteral:
        assert self.is_allocated(base_ptr)
        assert base_ptr.offset is not None
        return IRLiteral(self.allocated[base_ptr.source][0] + base_ptr.offset)

    def start_fn_allocation(self, fn):
        self.reserved = set()
        self.current_function = fn
        self.eom = MemoryAllocator.FN_START
        self.allocated_fn = OrderedSet()

    def add_allocated(self, mems: list[BasePtr]):
        self.allocated_fn.addmany(mems)

    def end_fn_allocation(self):
        self.mems_used[self.current_function] = OrderedSet(
            base_ptr.source for base_ptr in self.allocated_fn
        )

    def reset(self):
        self.reserved = set()
        self.eom = MemoryAllocator.FN_START

    def reserve(self, mem_loc: BasePtr):
        assert mem_loc.source in self.allocated
        ptr, size = self.allocated[mem_loc.source]
        self.reserved.add((ptr, size))
        self.eom = max(ptr + size, self.eom)

    def reserve_all(self):
        for mem in self.allocated_fn:
            self.reserve(mem)

from typing import Iterator

from vyper.evm.address_space import MEMORY
from vyper.utils import OrderedSet
from vyper.venom.analysis import BasePtrAnalysis, CFGAnalysis
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.memory_location import MemoryLocation

LatticeItem = OrderedSet[MemoryLocation]


def join(a: LatticeItem, b: LatticeItem) -> LatticeItem:
    assert isinstance(a, OrderedSet) and isinstance(b, OrderedSet)
    tmp = OrderedSet.intersection(a, b)
    assert isinstance(tmp, OrderedSet)
    return tmp


def carve_out(write: MemoryLocation, read: MemoryLocation) -> list[MemoryLocation]:
    if not MemoryLocation.may_overlap(read, write):
        return [write]
    if not read.is_fixed or not write.is_fixed:
        return [MemoryLocation.EMPTY]

    assert read.offset is not None
    assert write.offset is not None
    assert read.size is not None
    assert write.size is not None

    a = (write.offset, read.offset)
    b = (read.offset + read.size, write.offset + write.size)
    res = []
    if a[0] < a[1]:
        res.append(MemoryLocation(offset=a[0], size=a[1] - a[0]))
    if b[0] < b[1]:
        res.append(MemoryLocation(offset=b[0], size=b[1] - b[0]))
    return res


class MemOverwriteAnalysis(IRAnalysis):
    mem_overwritten: dict[IRBasicBlock, LatticeItem]
    mem_start: dict[IRBasicBlock, LatticeItem]

    def analyze(self):
        # Initialize with TOP (ALL) for backward must-analysis.
        # This ensures loops converge correctly - starting with "everything
        # overwritten" and refining via intersection.
        self.mem_overwritten = {
            bb: OrderedSet([MemoryLocation.ALL]) for bb in self.function.get_basic_blocks()
        }
        self.mem_start = {bb: OrderedSet() for bb in self.function.get_basic_blocks()}
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)

        order = self.cfg.dfs_post_walk

        while True:
            change = False
            for bb in order:
                res = self._handle_bb(bb)
                if self.mem_overwritten[bb] != res:
                    change = True
                    self.mem_overwritten[bb] = res

            if not change:
                break

    def _apply_transfer(self, inst: IRInstruction, lattice_item: LatticeItem) -> LatticeItem:
        """
        Apply backward transfer function for one instruction.
        Returns the updated lattice item.
        """
        read_loc = self.base_ptrs.get_read_location(inst, MEMORY)
        write_loc = self.base_ptrs.get_write_location(inst, MEMORY)

        if write_loc != MemoryLocation.EMPTY and write_loc.is_fixed:
            lattice_item.add(write_loc)

        if not read_loc.is_fixed:
            return OrderedSet()

        if read_loc.is_fixed:
            tmp: LatticeItem = OrderedSet()
            for loc in lattice_item:
                tmp.addmany(carve_out(write=loc, read=read_loc))
            return tmp

        return lattice_item

    def _handle_bb(self, bb: IRBasicBlock) -> LatticeItem:
        succs = self.cfg.cfg_out(bb)
        lattice_item: LatticeItem
        if len(succs) > 0:
            lattice_item = self.mem_overwritten[succs.first()].copy()
            for succ in self.cfg.cfg_out(bb):
                lattice_item = join(lattice_item, self.mem_overwritten[succ])
        elif bb.instructions[-1].opcode in ("stop", "sink"):
            lattice_item = OrderedSet([MemoryLocation.ALL])
        else:
            lattice_item = OrderedSet([])

        self.mem_start[bb] = lattice_item

        for inst in reversed(bb.instructions):
            lattice_item = self._apply_transfer(inst, lattice_item)

        return lattice_item

    def bb_iterator(self, bb: IRBasicBlock) -> Iterator[tuple[IRInstruction, LatticeItem]]:
        lattice_item = self.mem_start[bb]
        for inst in reversed(bb.instructions):
            yield (inst, lattice_item)
            lattice_item = self._apply_transfer(inst, lattice_item)

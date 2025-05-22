import dataclasses as dc
from typing import Optional

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.memory_location import MemoryLocation, get_read_location, get_write_location


class MemoryAliasAnalysisAbstract(IRAnalysis):
    """
    Analyzes memory operations to determine which locations may alias.
    This helps optimize memory operations by identifying when different
    memory accesses are guaranteed not to overlap.
    """

    addr_space: AddrSpace

    def analyze(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        # Map from memory locations to sets of potentially aliasing locations
        self.alias_sets: dict[MemoryLocation, OrderedSet[MemoryLocation]] = {}

        # Analyze all memory operations
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._analyze_instruction(inst)

    def _analyze_instruction(self, inst: IRInstruction):
        """Analyze a memory instruction to determine aliasing"""
        loc: Optional[MemoryLocation] = None

        loc = get_read_location(inst, self.addr_space)
        if loc is not None:
            self._analyze_mem_location(loc)

        loc = get_write_location(inst, self.addr_space)
        if loc is not None:
            self._analyze_mem_location(loc)

    def _analyze_mem_location(self, loc: MemoryLocation):
        """Analyze a memory location to determine aliasing"""
        if loc not in self.alias_sets:
            self.alias_sets[loc] = OrderedSet()

        # Check for aliasing with existing locations
        for other_loc in self.alias_sets:
            if MemoryLocation.may_overlap(loc, other_loc):
                self.alias_sets[loc].add(other_loc)
                self.alias_sets[other_loc].add(loc)

    def may_alias(self, loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        """
        Determine if two memory locations may alias.
        """
        if loc1.is_volatile or loc2.is_volatile:
            return MemoryLocation.may_overlap(loc1, loc2)

        if loc1 in self.alias_sets and loc2 in self.alias_sets:
            return loc2 in self.alias_sets[loc1]

        result = MemoryLocation.may_overlap(loc1, loc2)

        if loc1 not in self.alias_sets:
            self._analyze_mem_location(loc1)
        if loc2 not in self.alias_sets:
            self._analyze_mem_location(loc2)

        return result

    def mark_volatile(self, loc: MemoryLocation) -> MemoryLocation:
        volatile_loc = dc.replace(loc, is_volatile=True)

        if loc in self.alias_sets:
            self.alias_sets[volatile_loc] = OrderedSet([volatile_loc])

            # new and old locations are aliased
            self.alias_sets[volatile_loc].add(loc)
            self.alias_sets[loc].add(volatile_loc)

            # copy aliasing relationships
            for other_loc in self.alias_sets[loc]:
                if other_loc != loc and other_loc != volatile_loc:
                    self.alias_sets[volatile_loc].add(other_loc)
                    self.alias_sets[other_loc].add(volatile_loc)

        return volatile_loc


class MemoryAliasAnalysis(MemoryAliasAnalysisAbstract):
    addr_space = MEMORY


class StorageAliasAnalysis(MemoryAliasAnalysisAbstract):
    addr_space = STORAGE


class TransientAliasAnalysis(MemoryAliasAnalysisAbstract):
    addr_space = TRANSIENT


def mem_alias_type_factory(addr_space: AddrSpace) -> type[MemoryAliasAnalysisAbstract]:
    if addr_space == MEMORY:
        return MemoryAliasAnalysis
    elif addr_space == STORAGE:
        return StorageAliasAnalysis
    elif addr_space == TRANSIENT:
        return TransientAliasAnalysis
    else:  # pragma: nocover
        raise ValueError(f"Invalid address space: {addr_space}")

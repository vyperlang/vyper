import bisect
from typing import Optional

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.utils import OrderedSet
from vyper.venom.analysis import BasePtrAnalysis, CFGAnalysis, DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.memory_location import Allocation, MemoryLocation


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
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)

        # Map from memory locations to sets of potentially aliasing locations
        self.alias_sets: dict[MemoryLocation, OrderedSet[MemoryLocation]] = {}
        self.concrete_locs: set[MemoryLocation] = set()
        self.abstract_locs: dict[Allocation, list[MemoryLocation]] = dict()

        # Analyze all memory operations
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._analyze_instruction(inst)

    def _analyze_instruction(self, inst: IRInstruction):
        """Analyze a memory instruction to determine aliasing"""
        loc: Optional[MemoryLocation] = None

        loc = self.base_ptr.get_read_location(inst, self.addr_space)
        if loc is not None:
            self._analyze_mem_location(loc)

        loc = self.base_ptr.get_write_location(inst, self.addr_space)
        if loc is not None:
            self._analyze_mem_location(loc)

    def _analyze_mem_location(self, loc: MemoryLocation):
        """Analyze a memory location to determine aliasing"""
        if loc not in self.alias_sets:
            self.alias_sets[loc] = OrderedSet()

        if not loc.is_concrete:
            self._analyze_abstract_mem_location(loc)
            return

        self.concrete_locs.add(loc)

        # Check for aliasing with existing locations
        # NOTE: This is O(n) per location, resulting in O(n^2) total for n locations.
        # For large contracts, consider using an interval tree or immutable set
        # data structure to improve lookup performance.
        for other_loc in self.alias_sets:
            if MemoryLocation.may_overlap(loc, other_loc):
                self.alias_sets[loc].add(other_loc)
                self.alias_sets[other_loc].add(loc)

    def insert_memloc(self, loc: MemoryLocation):
        assert loc.alloca is not None
        if loc.alloca not in self.abstract_locs:
            self.abstract_locs[loc.alloca] = []

        def key(item: MemoryLocation) -> int:
            if item.size is None or item.offset is None:
                return 2**256
            return item.size + item.offset

        alloca_list = self.abstract_locs[loc.alloca]
        index = bisect.bisect_left(alloca_list, key(loc), key=key)
        if len(alloca_list) <= index or alloca_list[index] != loc:
            alloca_list.insert(index, loc)
        offset = 0 if loc.offset is None else loc.offset
        return bisect.bisect_left(alloca_list, offset, key=key)

    def _analyze_abstract_mem_location(self, loc: MemoryLocation):
        assert loc.alloca is not None
        index = self.insert_memloc(loc)

        for concrete_loc in self.concrete_locs:
            if MemoryLocation.may_overlap(loc, concrete_loc):
                self.alias_sets[loc].add(concrete_loc)
                self.alias_sets[concrete_loc].add(loc)

        for other_loc in self.abstract_locs[loc.alloca][index:]:
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

    def get_alias_set(self, loc: MemoryLocation) -> OrderedSet[MemoryLocation] | None:
        if loc not in self.alias_sets:
            self._analyze_mem_location(loc)
        return self.alias_sets.get(loc, None)

    def ensure_analyzed(self, loc: MemoryLocation):
        if loc not in self.alias_sets:
            self._analyze_mem_location(loc)

    def mark_volatile(self, loc: MemoryLocation) -> MemoryLocation:
        volatile_loc = loc.mk_volatile()

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

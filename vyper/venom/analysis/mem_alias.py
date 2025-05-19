import dataclasses as dc
from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import EMPTY_MEMORY_ACCESS, IRInstruction, MemoryLocation


class MemoryAliasAnalysis(IRAnalysis):
    """
    Analyzes memory operations to determine which locations may alias.
    This helps optimize memory operations by identifying when different
    memory accesses are guaranteed not to overlap.
    """

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

        loc = inst.get_read_memory_location()
        if loc is not None:
            self._analyze_mem_location(loc)

        loc = inst.get_write_memory_location()
        if loc is not None:
            self._analyze_mem_location(loc)

    def _analyze_mem_location(self, loc: MemoryLocation):
        """Analyze a memory location to determine aliasing"""
        if loc not in self.alias_sets:
            self.alias_sets[loc] = OrderedSet()

        # Check for aliasing with existing locations
        for other_loc in self.alias_sets:
            if self._may_alias(loc, other_loc):
                self.alias_sets[loc].add(other_loc)
                self.alias_sets[other_loc].add(loc)

    def _may_alias(self, loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        """
        Determine if two memory locations alias.
        """
        if loc1 == EMPTY_MEMORY_ACCESS or loc2 == EMPTY_MEMORY_ACCESS:
            return False

        o1, s1 = loc1.offset, loc1.size
        o2, s2 = loc2.offset, loc2.size

        # All known
        if loc1.is_fixed and loc2.is_fixed:
            end1 = o1 + s1  # type: ignore
            end2 = o2 + s2  # type: ignore
            return not (end1 <= o2 or end2 <= o1)  # type: ignore

        # If either size is zero, no alias
        if s1 == 0 or s2 == 0:
            return False

        # If both offsets are known
        if loc1.is_offset_fixed and loc2.is_offset_fixed:
            # loc1 known size, loc2 unknown size
            if loc1.is_size_fixed and not loc2.is_size_fixed:
                if o1 + s1 <= o2:  # type: ignore
                    return False
            # loc2 known size, loc1 unknown size
            if loc2.is_size_fixed and not loc1.is_size_fixed:
                if o2 + s2 <= o1:  # type: ignore
                    return False
            # Otherwise, can't be sure
            return True

        # If offsets are unknown, can't be sure
        return True

    def may_alias(self, loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        """
        Determine if two memory locations may alias.
        """
        if loc1.is_volatile or loc2.is_volatile:
            return self._may_alias(loc1, loc2)

        if loc1 in self.alias_sets and loc2 in self.alias_sets:
            return loc2 in self.alias_sets[loc1]

        result = self._may_alias(loc1, loc2)

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

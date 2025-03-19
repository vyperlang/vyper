from dataclasses import dataclass
from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import EMPTY_MEMORY_ACCESS, FULL_MEMORY_ACCESS, IRInstruction, IRLiteral, IROperand, IRVariable, MemoryLocation


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

        # Handle alloca instructions
        if inst.opcode == "alloca":
            assert inst.output is not None  # hint
            size = inst.operands[0].value if isinstance(inst.operands[0], IRLiteral) else 0
            offset = inst.operands[1].value if isinstance(inst.operands[1], IRLiteral) else 0
            loc = MemoryLocation(base=inst.output, offset=offset, size=size, is_alloca=True)
            self.alias_sets[loc] = OrderedSet([loc])
            return

        loc = inst.get_read_memory_location()
        if loc is not None:
            self._analyze_mem_location(loc)
        
        loc = inst.get_write_memory_location()
        if loc is not None:
            self._analyze_mem_location(loc)
    

    def _analyze_mem_location(self, loc: MemoryLocation):
        """Analyze a memory location to determine aliasing"""
        if loc not in self.alias_sets:
            self.alias_sets[loc] = OrderedSet([loc])

        # Check for aliasing with existing locations
        for other_loc in self.alias_sets:
            if self.may_alias(loc, other_loc):
                self.alias_sets[loc].add(other_loc)
                self.alias_sets[other_loc].add(loc)
    
    def may_alias(self, loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        """
        Determine if two memory locations alias.
        """
        if loc1 == FULL_MEMORY_ACCESS:
            return loc2 != EMPTY_MEMORY_ACCESS
        if loc2 == FULL_MEMORY_ACCESS:
            return loc1 != EMPTY_MEMORY_ACCESS
            
        if loc1 == EMPTY_MEMORY_ACCESS or loc2 == EMPTY_MEMORY_ACCESS:
            return False
            
        if loc1.size <= 0 or loc2.size <= 0:
            return False
            
        bases_match = False
        if isinstance(loc1.base, IRVariable) and isinstance(loc2.base, IRVariable):
            bases_match = loc1.base == loc2.base
        elif isinstance(loc1.base, IRLiteral) and isinstance(loc2.base, IRLiteral):
            bases_match = loc1.base.value == loc2.base.value
        else:
            return False  # Can't prove bases must match
            
        if not bases_match:
            return False
            
        start1, end1 = loc1.offset, loc1.offset + loc1.size
        start2, end2 = loc2.offset, loc2.offset + loc2.size
        
        return (start1 <= start2 < end1) or (start2 <= start1 < end2)

from dataclasses import dataclass
from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable


@dataclass(frozen=True)
class MemoryLocation:
    """Represents a memory location that can be analyzed for aliasing"""

    base: IROperand  # Base address
    offset: int = 0
    size: int = 0
    is_alloca: bool = False

FULL_MEMORY_ACCESS = MemoryLocation(base=IROperand(0), offset=0, size=-1, is_alloca=False)
EMPTY_MEMORY_ACCESS = MemoryLocation(base=IROperand(0), offset=0, size=0, is_alloca=False)

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
                if inst.opcode in ("mstore", "mload", "mcopy"):
                    self._analyze_mem_instruction(inst)

    def _analyze_mem_instruction(self, inst: IRInstruction):
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

        loc = self._get_memory_location(inst)
        if loc is None:
            return

        # Add to alias set
        if loc not in self.alias_sets:
            self.alias_sets[loc] = OrderedSet([loc])

        # Check for aliasing with existing locations
        for other_loc in self.alias_sets:
            if self._may_alias(loc, other_loc):
                self.alias_sets[loc].add(other_loc)
                self.alias_sets[other_loc].add(loc)

    def _get_write_memory_location(self, inst: IRInstruction) -> MemoryLocation:
        """Extract memory location info from an instruction"""
        opcode = inst.opcode
        if opcode == "mstore":
            addr = inst.operands[1]
            offset = addr.value if isinstance(addr, IRLiteral) else 0
            size = 32
            return MemoryLocation(addr, offset, size)
        elif opcode == "mload":
            return EMPTY_MEMORY_ACCESS
        elif opcode == "mcopy":
            return FULL_MEMORY_ACCESS
        elif opcode == "calldatacopy":
            return FULL_MEMORY_ACCESS
        elif opcode == "dloadbytes":
            return FULL_MEMORY_ACCESS
        elif opcode == "dload":
            return FULL_MEMORY_ACCESS
        elif opcode == "invoke":
            return FULL_MEMORY_ACCESS
        return EMPTY_MEMORY_ACCESS

    def _get_read_memory_location(self, inst: IRInstruction) -> MemoryLocation:
        """Extract memory location info from an instruction"""
        opcode = inst.opcode
        if opcode == "mstore":
            return EMPTY_MEMORY_ACCESS
        elif opcode == "mload":
            addr = inst.operands[0]
            offset = addr.value if isinstance(addr, IRLiteral) else 0
            size = 32
            return MemoryLocation(addr, offset, size)
        elif opcode == "mcopy":
            return FULL_MEMORY_ACCESS
        elif opcode == "calldatacopy":
            return EMPTY_MEMORY_ACCESS
        elif opcode == "dloadbytes":
            return FULL_MEMORY_ACCESS
        elif opcode == "dload":
            return FULL_MEMORY_ACCESS
        elif opcode == "invoke":
            return FULL_MEMORY_ACCESS
        return EMPTY_MEMORY_ACCESS


    def _may_alias(self, loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
        """Determine if two memory locations may alias"""
        if loc1.size > 0 and loc2.size > 0:
            start1, end1 = loc1.offset, loc1.offset + loc1.size
            start2, end2 = loc2.offset, loc2.offset + loc2.size

            return start1 <= end2 and start2 <= end1

        # If bases are the same variable, they may alias
        if isinstance(loc1.base, IRVariable) and isinstance(loc2.base, IRVariable):
            return loc1.base == loc2.base

        # Conservative - assume may alias if we can't prove otherwise
        return True
    
    def alias(self, loc1: MemoryLocation, loc2: MemoryLocation) -> bool:
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

    def may_alias(self, inst1: IRInstruction, inst2: IRInstruction) -> bool:
        """Public API to check if two memory instructions may alias"""
        loc1 = self._get_write_memory_location(inst1)
        loc2 = self._get_write_memory_location(inst2)
        if loc1 == FULL_MEMORY_ACCESS or loc2 == FULL_MEMORY_ACCESS:
            return True
        if loc1 is None or loc2 is None:
            return False
        return self._may_alias(loc1, loc2)

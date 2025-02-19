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

    def _get_memory_location(self, inst: IRInstruction) -> Optional[MemoryLocation]:
        """Extract memory location info from an instruction"""
        if inst.opcode == "mstore":
            addr = inst.operands[1]
            offset = addr.value if isinstance(addr, IRLiteral) else 0
            size = 32
            return MemoryLocation(addr, offset, size)
        elif inst.opcode == "mload":
            addr = inst.operands[0]
            offset = addr.value if isinstance(addr, IRLiteral) else 0
            size = 32
            return MemoryLocation(addr, offset, size)
        elif inst.opcode == "mcopy":
            dst = inst.operands[0]
            size = inst.operands[2].value if isinstance(inst.operands[2], IRLiteral) else 0
            return MemoryLocation(dst, 0, size)
        return None

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

    def may_alias(self, inst1: IRInstruction, inst2: IRInstruction) -> bool:
        """Public API to check if two memory instructions may alias"""
        loc1 = self._get_memory_location(inst1)
        loc2 = self._get_memory_location(inst2)
        if loc1 is None or loc2 is None:
            return False
        return self._may_alias(loc1, loc2)

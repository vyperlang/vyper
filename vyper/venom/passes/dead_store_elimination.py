from typing import Literal
from vyper.utils import OrderedSet
from vyper.venom.analysis import DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef, StorageSSA
from vyper.venom.basicblock import IRInstruction
from vyper.venom.effects import NON_MEMORY_EFFECTS, NON_STORAGE_EFFECTS
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class DeadStoreElimination(IRPass):
    """
    This pass eliminates dead stores using Memory SSA analysis.
    """

    def run_pass(self, location_type: Literal["memory", "storage"] = "memory"):
        if location_type == "memory":
            MemSSAType = MemSSA
            self.NON_RELATED_EFFECTS = NON_MEMORY_EFFECTS
        elif location_type == "storage":
            MemSSAType = StorageSSA
            self.NON_RELATED_EFFECTS = NON_STORAGE_EFFECTS

        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.mem_ssa = self.analyses_cache.request_analysis(MemSSAType)

        self.updater = InstUpdater(self.dfg)
        self.used_defs = OrderedSet[MemoryDef]()

        # Generate the set of memory definitions that are used by
        # going through all memory uses and adding the memory definitions
        # that are aliasing with them
        for _, mem_uses in self.mem_ssa.memory_uses.items():
            for mem_use in mem_uses:
                aliased_accesses = self.mem_ssa.get_aliased_memory_accesses(mem_use)
                for aliased_access in aliased_accesses:
                    self.used_defs.add(aliased_access)

        # Go through all memory definitions and eliminate dead stores
        for mem_def in self.mem_ssa.get_memory_defs():
            if self._is_dead_store(mem_def):
                self.updater.nop(mem_def.store_inst, annotation="[dead store elimination]")

        self.analyses_cache.invalidate_analysis(MemSSAType)

    def _has_uses(self, inst: IRInstruction):
        """
        Checks if the instruction's output is used in the DFG.
        """
        return inst.output is not None and len(self.dfg.get_uses(inst.output)) > 0

    def _is_dead_store(self, mem_def: MemoryDef) -> bool:
        """
        Checks if the memory definition is a dead store.
        """

        # Volatile memory locations are never dead stores.
        if mem_def.loc.is_volatile is True:
            return False

        # Memory locations with unknown offset or size are never dead stores.
        if not mem_def.loc.is_fixed:
            return False

        # If the instruction output is used, it is not a dead store.
        if self._has_uses(mem_def.store_inst):
            return False

        # If the instruction has other effects than writing to memory,
        # it is not a dead store.
        inst = mem_def.store_inst
        write_effects = inst.get_write_effects()
        read_effects = inst.get_read_effects()
        has_other_effects = (write_effects | read_effects) & self.NON_RELATED_EFFECTS

        if has_other_effects:
            return False

        # If the memory definition is not used, it is a dead store.
        if mem_def not in self.used_defs:
            return True

        # If the memory definition is clobbered by another memory access,
        # it is a dead store.
        return self.mem_ssa.get_clobbering_memory_access(mem_def) is not None

from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.effects import NON_MEMORY_EFFECTS
from vyper.venom.passes.base_pass import InstUpdater, IRPass

class DeadStoreElimination(IRPass):
    """
    This pass eliminates dead stores using Memory SSA analysis.
    """

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)
        self.used_defs = OrderedSet[MemoryDef]()

        for _, mem_uses in self.mem_ssa.memory_uses.items():
            for mem_use in mem_uses:
                aliased_accesses = self.mem_ssa.get_aliased_memory_accesses(mem_use)
                for aliased_access in aliased_accesses:
                    self.used_defs.add(aliased_access)

        for mem_def in self.mem_ssa.get_memory_defs():
            if self._is_dead_store(mem_def):
                self.updater.nop(mem_def.store_inst, annotation="[dead store elimination]")

        self.analyses_cache.invalidate_analysis(MemSSA)

    def _has_uses(self, inst: IRInstruction):
        return inst.output is not None and len(self.dfg.get_uses(inst.output)) > 0

    def _is_dead_store(self, mem_def: MemoryDef) -> bool:
        if mem_def.loc.is_volatile is True:
            return False

        if mem_def.loc.offset == -1 or mem_def.loc.size == -1:
            return False

        if self._has_uses(mem_def.store_inst):
            return False

        inst = mem_def.store_inst
        write_effects = inst.get_write_effects()
        read_effects = inst.get_read_effects()
        has_other_effects = write_effects & NON_MEMORY_EFFECTS or read_effects & NON_MEMORY_EFFECTS

        if has_other_effects:
            return False

        if mem_def not in self.used_defs:
            return True

        clobbered_by = self.mem_ssa.get_clobbering_memory_access(mem_def)

        return clobbered_by is not None


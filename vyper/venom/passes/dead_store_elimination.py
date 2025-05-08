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
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)

        with self.mem_ssa.print_context():
            print("------------------------")
            print(self.function)

        self.dead_stores = OrderedSet[IRInstruction]()
        self.all_defs = self._collect_all_defs()

        self._identify_dead_stores()
        self._remove_dead_stores()

    def _identify_dead_stores(self):
        """
        Analyzes each basic block to find stores that are overwritten before
        being used or have no effect on the program's behavior.
        """
        live_defs = OrderedSet[MemoryDef]()
        dead_defs = OrderedSet[MemoryDef]()
        for bb in self.function.get_basic_blocks():            
            for inst in reversed(bb.instructions):
                mem_def = self.mem_ssa.get_memory_def(inst)
                mem_use = self.mem_ssa.get_memory_use(inst)

                write_effects = inst.get_write_effects()
                read_effects = inst.get_read_effects()
                has_other_effects = (
                    write_effects & NON_MEMORY_EFFECTS or read_effects & NON_MEMORY_EFFECTS
                )

                if mem_use is not None:
                    aliased_accesses = self.mem_ssa.get_aliased_memory_accesses(mem_use)
                    for aliased_access in aliased_accesses:
                        live_defs.add(aliased_access)

                if mem_def is not None:
                    clobbered_by = self.mem_ssa.get_clobbering_memory_access(mem_def)
                    if clobbered_by is not None:
                        dead_defs.add(mem_def)
                    elif has_other_effects or mem_def.loc.is_volatile or self._has_uses(inst.output):
                        live_defs.add(mem_def)
                        
        self.live_defs = live_defs - dead_defs

    def _has_uses(self, var: Optional[IRVariable]):
        return var is not None and len(self.dfg.get_uses(var)) > 0

    def _is_dead_store(
        self, inst: IRInstruction, mem_def: MemoryDef, live_defs: set[MemoryDef]
    ) -> bool:
        if self._has_uses(inst.output):
            return False

        clobbered_by = self.mem_ssa.get_clobbering_memory_access(mem_def)

        return (
            mem_def not in live_defs
            and (clobbered_by is not None)
            and not clobbered_by.is_live_on_entry
            and not clobbered_by.is_volatile
        )

    def _remove_dead_stores(self):
        """
        Removes all identified dead stores from the IR and updates the memory SSA information
        accordingly.
        """
        dead_defs = self.all_defs - self.live_defs
        for def_ in dead_defs:
            self.updater.nop(def_.store_inst, annotation="[dead store elimination]")

    def _collect_all_defs(self) -> OrderedSet[MemoryDef]:
        """
        Gathers all memory definitions across all basic blocks in the program.
        """
        all_defs = OrderedSet[MemoryDef]()
        for block in self.function.get_basic_blocks():
            if block in self.mem_ssa.memory_defs:
                all_defs.update(self.mem_ssa.memory_defs[block])
        return all_defs


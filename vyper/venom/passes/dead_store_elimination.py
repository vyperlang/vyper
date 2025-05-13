from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef, MemoryPhi
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

        self.dead_stores = OrderedSet[IRInstruction]()
        self.all_defs = self._collect_all_defs()

        self.used_defs = OrderedSet[MemoryDef]()
        dead_defs = OrderedSet[MemoryDef]()

        # with self.mem_ssa.print_context():
        #     print("------------------------")
        #     print(self.function)

        self.live_defs = OrderedSet()
        for use in self.mem_ssa.get_memory_uses():
            self.live_defs.add(use.reaching_def)

        processed_defs = OrderedSet()
        worklist = OrderedSet(self.live_defs)

        while len(worklist) > 0:
            current = worklist.pop()
            if current in processed_defs:
                continue
            processed_defs.add(current)

            if isinstance(current, MemoryDef):
                if self._is_dead_store(current) == True:
                    continue
                self.live_defs.add(current)
                if self.mem_ssa.memalias.may_alias(current.loc, current.reaching_def.loc):
                    worklist.add(current.reaching_def)
            elif isinstance(current, MemoryPhi):
                for access, _ in current.operands:
                    worklist.add(access)

        for mem_def in self.all_defs:
            if mem_def not in self.live_defs:
                dead_defs.add(mem_def)

        for def_ in dead_defs:
            self.updater.nop(def_.store_inst, annotation="[dead store elimination]")

        

    def _has_uses(self, var: Optional[IRVariable]):
        return var is not None and len(self.dfg.get_uses(var)) > 0

    def _is_dead_store(self, mem_def: MemoryDef) -> bool:
        if self._has_uses(mem_def.store_inst.output):
            return False

        if mem_def.loc.is_volatile is True:
            return False

        inst = mem_def.store_inst
        write_effects = inst.get_write_effects()
        read_effects = inst.get_read_effects()
        has_other_effects = write_effects & NON_MEMORY_EFFECTS or read_effects & NON_MEMORY_EFFECTS

        if has_other_effects:
            return False

        return True

        clobbered_by = self.mem_ssa.get_clobbering_memory_access(mem_def)

        return clobbered_by is not None and not clobbered_by.is_volatile

    def _collect_all_defs(self) -> OrderedSet[MemoryDef]:
        """
        Gathers all memory definitions across all basic blocks in the program.
        """
        all_defs = OrderedSet[MemoryDef]()
        for block in self.function.get_basic_blocks():
            if block in self.mem_ssa.memory_defs:
                all_defs.update(self.mem_ssa.memory_defs[block])
        return all_defs

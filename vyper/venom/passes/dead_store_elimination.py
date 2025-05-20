from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.effects import MEMORY, NON_MEMORY_EFFECTS
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class DeadStoreElimination(IRPass):
    """
    This pass eliminates dead stores using Memory SSA analysis.
    """

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)
        self.used_defs = OrderedSet[MemoryDef]()

        # Go through all memory definitions and eliminate dead stores
        for mem_def in self.mem_ssa.get_memory_defs():
            if self._is_dead_store(mem_def):
                self.updater.nop(mem_def.store_inst, annotation="[dead store elimination]")

        self.analyses_cache.invalidate_analysis(MemSSA)

    def _has_uses(self, inst: IRInstruction):
        """
        Checks if the instruction's output is used in the DFG.
        """
        return inst.output is not None and len(self.dfg.get_uses(inst.output)) > 0

    def _is_mem_used(self, query_inst: IRInstruction) -> bool:
        query_loc = query_inst.get_write_memory_location()
        worklist: OrderedSet[IRBasicBlock] = OrderedSet()
        visited: OrderedSet[IRBasicBlock] = OrderedSet()

        next_inst_idx = query_inst.parent.instructions.index(query_inst) + 1
        worklist.add(query_inst.parent)

        while len(worklist) > 0:
            bb = worklist.pop()

            clobbered = False
            for inst in bb.instructions[next_inst_idx:]:
                is_write = inst.get_write_effects() & MEMORY
                is_read = inst.get_read_effects() & MEMORY

                if is_read:
                    read_loc = inst.get_read_memory_location()
                    if self.mem_ssa.memalias.may_alias(read_loc, query_loc):
                        return True

                if is_write:
                    write_loc = inst.get_write_memory_location()
                    if write_loc.completely_contains(query_loc):
                        clobbered = True
                        break

            if clobbered:
                continue

            next_inst_idx = 0
            outs = self.cfg.cfg_out(bb)
            for out in outs:
                if out not in visited:
                    visited.add(out)
                    worklist.add(out)

        return False

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
        has_other_effects = (write_effects | read_effects) & NON_MEMORY_EFFECTS

        if has_other_effects:
            return False

        # If the memory definition is clobbered by another memory access,
        # it is a dead store.
        return not self._is_mem_used(mem_def.store_inst)

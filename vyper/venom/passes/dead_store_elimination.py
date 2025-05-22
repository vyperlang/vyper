from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.effects import NON_MEMORY_EFFECTS
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

    def _is_memory_def_live(self, mem_def: MemoryDef) -> bool:
        """
        Checks if the memory definition is live by checking if it is
        read from in any of the blocks that are reachable from the
        memory definition's block, without being clobbered by another
        memory access before read.
        """
        query_loc = mem_def.loc
        worklist: OrderedSet[IRBasicBlock] = OrderedSet()

        # blocks not to visit
        visited: OrderedSet[IRBasicBlock] = OrderedSet()

        # for the first block, we start from the instruction after mem_def.inst
        next_inst_idx = mem_def.inst.parent.instructions.index(mem_def.inst) + 1

        # we don't add this to visited because in the case of a loop
        # (bb is reachable from itself), we want to be able to visit it again
        # starting from instruction 0.
        worklist.add(mem_def.inst.parent)

        while len(worklist) > 0:
            bb = worklist.pop()

            clobbered = False
            for inst in bb.instructions[next_inst_idx:]:
                # Check if the instruction reads from the memory location
                # If so, the memory definition is used.
                mem_use = self.mem_ssa.get_memory_use(inst)
                if mem_use is not None:
                    read_loc = mem_use.loc
                    if self.mem_ssa.memalias.may_alias(read_loc, query_loc):
                        return True

                # Check if the instruction writes to the memory location
                # and it clobbers the memory definition. In this case,
                # we continue to the next block already in the worklist.
                mem_def = self.mem_ssa.get_memory_def(inst)
                if mem_def is not None:
                    write_loc = mem_def.loc
                    if write_loc.completely_contains(query_loc):
                        clobbered = True
                        break

            # If the memory definition is clobbered, we continue to
            # the next block already in the worklist without adding
            # its offspring to the worklist.
            if clobbered:
                continue

            # Otherwise, we add the block's offsprings to the worklist.
            # for all successor blocks, start from the 0'th instruction
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
        return not self._is_memory_def_live(mem_def)

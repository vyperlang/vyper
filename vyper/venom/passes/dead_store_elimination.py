from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryAccess, MemoryDef
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, MemoryLocation
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

        # ΤΕΣΤ
        self.mem_ssa.mark_location_volatile(
            MemoryLocation(offset=0xFFFF0000, size=32, is_alloca=False, is_volatile=True)
        )

        self.dead_stores = OrderedSet[IRInstruction]()
        self._preprocess_never_used_stores()
        self._identify_dead_stores()
        self._remove_dead_stores()

    def _preprocess_never_used_stores(self):
        all_defs = OrderedSet[MemoryDef]()
        for bb in self.cfg.dfs_pre_walk:
            if bb in self.mem_ssa.memory_defs:
                all_defs.update(self.mem_ssa.memory_defs[bb])

        used_defs = OrderedSet[MemoryDef]()
        for bb in self.cfg.dfs_pre_walk:
            if bb in self.mem_ssa.memory_uses:
                for mem_use in self.mem_ssa.memory_uses[bb]:
                    if mem_use.reaching_def and isinstance(mem_use.reaching_def, MemoryDef):
                        used_defs.add(mem_use.reaching_def)

            for succ in bb.cfg_out:
                if succ in self.mem_ssa.memory_phis:
                    phi = self.mem_ssa.memory_phis[succ]
                    for op_def, pred in phi.operands:
                        if pred == bb and op_def in self.mem_ssa.memory_defs.get(bb, []):
                            used_defs.add(op_def)

        never_used_defs = all_defs - used_defs
        for mem_def in never_used_defs:
            if mem_def.loc.is_volatile:
                continue
            self.dead_stores.add(mem_def.store_inst)

    def _identify_dead_stores(self):
        for bb in self.cfg.dfs_pre_walk:
            if bb not in self.mem_ssa.memory_defs:
                continue

            live_defs = OrderedSet[MemoryDef]()
            for inst in reversed(bb.instructions):
                mem_def = self.mem_ssa.get_memory_def(inst)
                mem_use = self.mem_ssa.get_memory_use(inst)

                if mem_use and mem_use.reaching_def:
                    if isinstance(mem_use.reaching_def, MemoryDef):
                        live_defs.add(mem_use.reaching_def)

                if mem_def and not mem_def.loc.is_volatile:
                    clobbered_by = self.mem_ssa.get_clobbering_memory_access(mem_def)
                    if (
                        mem_def not in live_defs
                        and clobbered_by
                        and not clobbered_by.is_live_on_entry
                    ):
                        self.dead_stores.add(inst)
            for inst in bb.instructions:
                mem_def = self.mem_ssa.get_memory_def(inst)
                if mem_def and mem_def in live_defs and inst in self.dead_stores:
                    self.dead_stores.remove(inst)

    def _get_previous_def(self, bb: IRBasicBlock) -> Optional[MemoryAccess]:
        if bb in self.mem_ssa.memory_defs and self.mem_ssa.memory_defs[bb]:
            return self.mem_ssa.memory_defs[bb][-1]
        if bb in self.mem_ssa.memory_phis:
            return self.mem_ssa.memory_phis[bb]
        if bb.cfg_in:
            idom = self.mem_ssa.dom.immediate_dominators.get(bb)
            return self.mem_ssa._get_in_def(idom) if idom else self.mem_ssa.live_on_entry
        return self.mem_ssa.live_on_entry

    def _remove_dead_stores(self):
        """Remove identified dead stores from the IR"""
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst in self.dead_stores:
                    self.updater.nop(inst, "[dead store elimination]")
            if bb in self.mem_ssa.memory_defs:
                self.mem_ssa.memory_defs[bb] = [
                    mem_def
                    for mem_def in self.mem_ssa.memory_defs[bb]
                    if mem_def.store_inst not in self.dead_stores
                ]
                if (
                    self.mem_ssa.current_def.get(bb)
                    and self.mem_ssa.current_def[bb].store_inst in self.dead_stores
                ):
                    self.mem_ssa.current_def[bb] = self._get_previous_def(bb)

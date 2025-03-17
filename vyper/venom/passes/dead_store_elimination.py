from vyper.venom.analysis import DFGAnalysis, MemSSA
from vyper.venom.basicblock import IRLiteral
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class DeadStoreElimination(IRPass):
    """
    This pass eliminates dead stores using Memory SSA analysis.
    A store is considered dead if:
    1. Its value is never used (no loads read from it before the next store)
    2. It is overwritten by another store to exactly the same location
       (exact pointer equality, not just may_alias)
    """

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

    def _process_basic_block(self, bb):
        if bb not in self.mem_ssa.memory_defs:
            return

        mem_defs = self.mem_ssa.memory_defs[bb]

        for mem_def in mem_defs:
            if self._is_dead_store(mem_def):
                self.updater.nop(mem_def.store_inst)

    def _is_dead_store(self, mem_def) -> bool:
        store_inst = mem_def.store_inst
        bb = store_inst.parent

        for _use_bb, uses in self.mem_ssa.memory_uses.items():
            for use in uses:
                if use.reaching_def == mem_def:
                    return False

        if bb in self.mem_ssa.memory_defs:
            defs = self.mem_ssa.memory_defs[bb]
            for next_def in defs:
                if next_def.version <= mem_def.version:
                    continue

                store_addr = (
                    store_inst.operands[1]
                    if store_inst.opcode == "mstore"
                    else store_inst.operands[0]
                )
                next_addr = (
                    next_def.store_inst.operands[1]
                    if next_def.store_inst.opcode == "mstore"
                    else next_def.store_inst.operands[0]
                )
                if (
                    isinstance(store_addr, IRLiteral)
                    and isinstance(next_addr, IRLiteral)
                    and store_addr.value == next_addr.value
                ):
                    return True

        return False

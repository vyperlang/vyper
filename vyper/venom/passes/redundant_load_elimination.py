from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryUse
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class RedundantLoadElimination(IRPass):
    """
    This pass eliminates redundant mload instructions using Memory SSA analysis.
    """
    
    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)

        self.redundant_loads = OrderedSet[tuple[IRInstruction, IRInstruction]]()
        self._identify_redundant_loads()
        self._remove_redundant_loads()

    def _identify_redundant_loads(self):
        for bb in self.cfg.dfs_pre_walk:
            if bb not in self.mem_ssa.memory_uses:
                continue

            available_loads = OrderedSet[tuple[MemoryUse, IRInstruction]]()

            for inst in bb.instructions:
                if inst.opcode != "mload":
                    continue

                mem_use = self.mem_ssa.get_memory_use(inst)

                if mem_use and not mem_use.loc.is_volatile:
                    for prev_use, prev_inst in available_loads:
                        if (
                            self.mem_ssa.alias.may_alias(mem_use.loc, prev_use.loc)
                            and not mem_use.loc.is_volatile
                            and not prev_use.loc.is_volatile
                        ):
                            self.redundant_loads.add((inst, prev_inst))
                            break

                    if not any(inst == red_load[0] for red_load in self.redundant_loads):
                        available_loads.add((mem_use, inst))

    def _remove_redundant_loads(self):
        for redundant_load, prev_load in self.redundant_loads:
            self.updater.update(
                redundant_load, "store", [prev_load.output], "[redundant mload elimination]"
            )

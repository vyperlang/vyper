from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class BranchOptimizationPass(IRPass):
    """
    This pass optimizes branches inverting jnz instructions where appropriate
    """

    def _optimize_branches(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            term_inst = bb.instructions[-1]
            if term_inst.opcode != "jnz":
                continue

            fst, snd = bb.cfg_out

            fst_liveness = fst.instructions[0].liveness
            snd_liveness = snd.instructions[0].liveness

            cost_a, cost_b = len(fst_liveness), len(snd_liveness)

            cond = term_inst.operands[0]
            prev_inst = self.dfg.get_producing_instruction(cond)
            if cost_a >= cost_b and prev_inst.opcode == "iszero":
                new_cond = prev_inst.operands[0]
                new_operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
                self.updater.update(term_inst, term_inst.opcode, new_operands)
            elif cost_a > cost_b:
                new_cond = self.updater.add_before(term_inst, "iszero", [term_inst.operands[0]])
                new_operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
                self.updater.update(term_inst, term_inst.opcode, new_operands)

    def run_pass(self):
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        self._optimize_branches()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)

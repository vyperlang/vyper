from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.passes.base_pass import IRPass


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

            prev_inst = self.dfg.get_producing_instruction(term_inst.operands[0])
            if prev_inst.opcode == "iszero":
                new_cond = prev_inst.operands[0]
                term_inst.operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]

                # Since the DFG update is simple we do in place to avoid invalidating the DFG
                # and having to recompute it (which is expensive(er))
                self.dfg.remove_use(prev_inst.output, term_inst)
                self.dfg.add_use(new_cond, term_inst)

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._optimize_branches()

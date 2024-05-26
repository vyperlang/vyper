from vyper.venom.analysis.cfg import CFGAnalysis
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
                term_inst.operands = [
                    prev_inst.operands[0],
                    term_inst.operands[2],
                    term_inst.operands[1],
                ]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._optimize_branches()

        self.analyses_cache.invalidate_analysis(CFGAnalysis)

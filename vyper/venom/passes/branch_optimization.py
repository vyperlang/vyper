from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
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

            iszero_chain = self._get_iszero_chain(term_inst.operands[0])
            if len(iszero_chain) == 0:
                continue

            if len(iszero_chain) % 2 == 0:
                prev_inst = iszero_chain[-2]
            else:
                prev_inst = iszero_chain[-1]

            term_inst.operands = [
                prev_inst.operands[0],
                term_inst.operands[2],
                term_inst.operands[1],
            ]

    def _get_iszero_chain(self, op: IRVariable) -> list[IRInstruction]:
        chain = []
        while True:
            inst = self.dfg.get_producing_instruction(op)
            if inst.opcode != "iszero":
                break
            if len(self.dfg.get_uses(inst.output)) != 1:
                break
            op = inst.operands[0]
            chain.append(inst)
        
        return chain
        
    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._optimize_branches()

        self.analyses_cache.invalidate_analysis(CFGAnalysis)
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass


# for these instruction exist optimization that
# could benefit from iszero
def prefer_iszero(inst: IRInstruction) -> bool:
    if inst.opcode == "eq":
        return True
    if inst.opcode in ["gt", "lt"]:
        return any(isinstance(op, IRLiteral) for op in inst.operands)
    return False


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
                term_inst.operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
            elif cost_a >= cost_b and prefer_iszero(prev_inst):
                new_cond = fn.get_next_variable()
                inst = IRInstruction("iszero", [term_inst.operands[0]], output=new_cond)
                bb.insert_instruction(inst, index=-1)
                term_inst.operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
            elif cost_a > cost_b:
                new_cond = fn.get_next_variable()
                inst = IRInstruction("iszero", [term_inst.operands[0]], output=new_cond)
                bb.insert_instruction(inst, index=-1)
                term_inst.operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]

    def run_pass(self):
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._optimize_branches()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)

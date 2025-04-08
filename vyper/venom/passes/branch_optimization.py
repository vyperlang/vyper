from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import COMPARATOR_INSTRUCTIONS, IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import InstUpdater, IRPass


# for these instruction exist optimization that
# could benefit from iszero
def prefer_iszero(inst: IRInstruction) -> bool:
    # TODO: is there something we can do with `xor`?
    if inst.opcode == "eq":
        return True
    if inst.opcode in COMPARATOR_INSTRUCTIONS:
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

            # heuristic(!) to decide if we should flip the labels or not
            cost_a, cost_b = len(fst_liveness), len(snd_liveness)

            cond = term_inst.operands[0]
            prev_inst = self.dfg.get_producing_instruction(cond)

            # heuristic: remove the iszero and swap branches
            if cost_a >= cost_b and prev_inst.opcode == "iszero":
                new_cond = prev_inst.operands[0]
                new_labels = term_inst.operands[2], term_inst.operands[1]
                self.updater.update(term_inst, "jnz", [new_cond, *new_labels])

            # heuristic: add an iszero and swap branches
            elif cost_a > cost_b or (cost_a >= cost_b and prefer_iszero(prev_inst)):
                new_cond = self.updater.add_before(term_inst, "iszero", [term_inst.operands[0]])
                new_labels = term_inst.operands[2], term_inst.operands[1]
                self.updater.update(term_inst, "jnz", [new_cond, *new_labels])

    def run_pass(self):
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        assert isinstance(self.dfg, DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        self._optimize_branches()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)

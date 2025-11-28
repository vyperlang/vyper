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

    cfg: CFGAnalysis
    liveness: LivenessAnalysis
    dfg: DFGAnalysis

    def _optimize_branches(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            term_inst = bb.instructions[-1]
            if term_inst.opcode != "jnz":
                continue

            fst, snd = self.cfg.cfg_out(bb)

            fst_liveness = self.liveness.live_vars_at(fst.instructions[0])
            snd_liveness = self.liveness.live_vars_at(snd.instructions[0])

            # heuristic(!) to decide if we should flip the labels or not
            cost_a, cost_b = len(fst_liveness), len(snd_liveness)

            cond = term_inst.operands[0]
            prev_inst = self.dfg.get_producing_instruction(cond)
            assert prev_inst is not None

            # heuristic: remove the iszero and swap branches
            if cost_a >= cost_b and prev_inst.opcode == "iszero":
                new_cond = prev_inst.operands[0]
                new_operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
                self.updater.update(term_inst, term_inst.opcode, new_operands)

            # heuristic: add an iszero and swap branches
            elif cost_a > cost_b or (cost_a >= cost_b and prefer_iszero(prev_inst)):
                tmp = self.updater.add_before(term_inst, "iszero", [term_inst.operands[0]])
                assert tmp is not None  # help mypy
                new_cond = tmp
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

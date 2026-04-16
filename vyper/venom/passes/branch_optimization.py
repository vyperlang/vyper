from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import COMPARATOR_INSTRUCTIONS, IRInstruction, IRLiteral, IRBasicBlock
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
    # Snapshot of the liveness state at the start of the pass
    # to be used in heuristic. Snapshot is created because the
    # pass alter the state of the function which can invalidate
    # the part of the state of the liveness analysis which would be
    # needed for heuristic.
    heuristic_liveness: dict[IRBasicBlock, OrderedSet]
    dfg: DFGAnalysis

    def _optimize_branches(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            term_inst = bb.instructions[-1]
            if term_inst.opcode != "jnz":
                continue

            fst, snd = self.cfg.cfg_out(bb)

            fst_liveness = self.heuristic_liveness[fst]
            snd_liveness = self.heuristic_liveness[snd]

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
        liveness = self.analyses_cache.request_analysis(LivenessAnalysis)

        self.heuristic_liveness = dict()
        for bb in self.function.get_basic_blocks():
            live_state = liveness.live_vars_at(bb.instructions[0])
            self.heuristic_liveness[bb] = live_state

        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        self._optimize_branches()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)

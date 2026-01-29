import os
import sys

from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.variable_range import ValueRange, VariableRangeAnalysis
from vyper.venom.basicblock import COMPARATOR_INSTRUCTIONS, IRInstruction, IRLiteral, IRVariable
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


def _range_excludes_zero(rng: ValueRange) -> bool:
    if rng.is_empty:
        return False
    return rng.lo > 0 or rng.hi < 0


class BranchOptimizationPass(IRPass):
    """
    This pass optimizes branches inverting jnz instructions where appropriate
    """

    cfg: CFGAnalysis
    liveness: LivenessAnalysis
    dfg: DFGAnalysis
    range_analysis: VariableRangeAnalysis

    def _optimize_branches(self) -> bool:
        changed = False
        fn = self.function
        for bb in fn.get_basic_blocks():
            term_inst = bb.instructions[-1]
            if term_inst.opcode != "jnz":
                continue

            self._jnz_seen += 1
            cond = term_inst.operands[0]
            rng = self.range_analysis.get_range(cond, term_inst)
            if self._trace_limit > 0 and self._trace_count < self._trace_limit:
                producer = None
                if isinstance(cond, IRVariable):
                    producer = self.dfg.get_producing_instruction(cond)
                producer_str = str(producer) if producer is not None else "None"
                self._trace_entries.append(
                    f"  {bb.label}: {term_inst} range={rng} producer={producer_str}"
                )
                self._trace_count += 1
            if _range_excludes_zero(rng):
                true_label = term_inst.operands[1]
                self.updater.update(term_inst, "jmp", [true_label])
                self._range_fold_true += 1
                changed = True
                continue
            if rng.is_constant and rng.lo == 0:
                false_label = term_inst.operands[2]
                self.updater.update(term_inst, "jmp", [false_label])
                self._range_fold_false += 1
                changed = True
                continue

            fst, snd = self.cfg.cfg_out(bb)

            fst_liveness = self.liveness.live_vars_at(fst.instructions[0])
            snd_liveness = self.liveness.live_vars_at(snd.instructions[0])

            # heuristic(!) to decide if we should flip the labels or not
            cost_a, cost_b = len(fst_liveness), len(snd_liveness)

            prev_inst = self.dfg.get_producing_instruction(cond)
            assert prev_inst is not None

            # heuristic: remove the iszero and swap branches
            if cost_a >= cost_b and prev_inst.opcode == "iszero":
                new_cond = prev_inst.operands[0]
                new_operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
                self.updater.update(term_inst, term_inst.opcode, new_operands)
                self._heuristic_flip += 1
                changed = True

            # heuristic: add an iszero and swap branches
            elif cost_a > cost_b or (cost_a >= cost_b and prefer_iszero(prev_inst)):
                tmp = self.updater.add_before(term_inst, "iszero", [term_inst.operands[0]])
                assert tmp is not None  # help mypy
                new_cond = tmp
                new_operands = [new_cond, term_inst.operands[2], term_inst.operands[1]]
                self.updater.update(term_inst, term_inst.opcode, new_operands)
                self._heuristic_insert += 1
                changed = True

        return changed

    def run_pass(self):
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.range_analysis = self.analyses_cache.force_analysis(VariableRangeAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._jnz_seen = 0
        self._range_fold_true = 0
        self._range_fold_false = 0
        self._heuristic_flip = 0
        self._heuristic_insert = 0
        self._trace_limit = int(os.environ.get("VYPER_VENOM_BRANCH_TRACE", "0") or 0)
        self._trace_count = 0
        self._trace_entries = []

        changed = self._optimize_branches()

        if os.environ.get("VYPER_VENOM_BRANCH_STATS"):
            fn_name = str(self.function.name)
            print(
                f"BranchOptimizationPass[{fn_name}]: jnz={self._jnz_seen} "
                f"range_true={self._range_fold_true} range_false={self._range_fold_false} "
                f"heuristic_flip={self._heuristic_flip} "
                f"heuristic_insert={self._heuristic_insert}",
                file=sys.stderr,
            )
        if self._trace_entries:
            fn_name = str(self.function.name)
            print(f"BranchOptimizationPassTrace[{fn_name}]:", file=sys.stderr)
            for entry in self._trace_entries:
                print(entry, file=sys.stderr)

        if changed:
            self.analyses_cache.invalidate_analysis(VariableRangeAnalysis)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)
            self.analyses_cache.invalidate_analysis(CFGAnalysis)

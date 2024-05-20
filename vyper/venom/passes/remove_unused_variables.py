from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.passes.base_pass import IRPass


class RemoveUnusedVariablesPass(IRPass):
    def run_pass(self):
        self.analyses_cache.request_analysis(LivenessAnalysis)

        for bb in self.function.get_basic_blocks():
            self._remove_unused_variables(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _remove_unused_variables(self, bb: IRBasicBlock):
        """
        Remove the instructions of a basicblock that produce output that is never used.
        """
        i = 0
        while i < len(bb.instructions) - 1:
            inst = bb.instructions[i]
            i += 1

            # Skip volatile instructions
            if inst.volatile:
                continue

            # Skip instructions without output
            if inst.output is None:
                continue

            # Skip instructions that produce output that is used
            next_liveness = bb.instructions[i].liveness
            if inst.output in next_liveness:
                continue

            # Remove the rest
            del bb.instructions[i - 1]
            i = max(0, i - 2)

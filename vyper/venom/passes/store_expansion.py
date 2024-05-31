from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.dominators import DominatorTreeAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import IRPass


class StoreExpansionPass(IRPass):
    """
    This pass expands variables to their uses though `store` instructions,
    reducing pressure on the stack scheduler
    """

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for bb in self.function.get_basic_blocks():
            for idx, inst in enumerate(bb.instructions):
                if inst.opcode != "store":
                    continue

                self._process_inst(dfg, inst, idx)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_inst(self, dfg, inst, idx):
        """
        Process store instruction. If the variable is only used by a load instruction,
        forward the variable to the load instruction.
        """
        var = inst.output
        uses = dfg.get_uses(var)

        insertion_idx = idx + 1

        for use_inst in uses:
            if use_inst.parent != inst.parent:
                continue

            for i, operand in enumerate(use_inst.operands):
                if operand == var:
                    new_var = self.function.get_next_variable()
                    new_inst = IRInstruction("store", [var], new_var)
                    inst.parent.insert_instruction(new_inst, insertion_idx)
                    insertion_idx += 1
                    use_inst.operands[i] = new_var

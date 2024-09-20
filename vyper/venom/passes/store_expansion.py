from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass


class StoreExpansionPass(IRPass):
    """
    This pass expands variables to their uses though `store` instructions,
    reducing pressure on the stack scheduler
    """

    def run_pass(self):
        return
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.analyses_cache.request_analysis(CFGAnalysis)
        liveness = self.analyses_cache.force_analysis(LivenessAnalysis)

        for bb in self.function.get_basic_blocks():
            if len(bb.instructions) == 0:
                continue

            for var in bb.instructions[0].liveness:
                self._process_var(dfg, bb, var, 0)

            for idx, inst in enumerate(bb.instructions):
                if inst.output is None:
                    continue

                self._process_var(dfg, bb, inst.output, idx + 1)

            bb.instructions.sort(key=lambda inst: inst.opcode not in ("phi", "param"))

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_var(self, dfg, bb, var, idx):
        """
        Process a variable, allocating a new variable for each use
        and copying it to the new instruction
        """
        uses = dfg.get_uses(var)

        _cache = {}

        for use_inst in uses:
            if use_inst.opcode == "phi":
                continue
            if use_inst.parent != bb:
                continue

            for i, operand in enumerate(use_inst.operands):
                if operand == var:
                    new_var = self.function.get_next_variable()
                    new_inst = IRInstruction("store", [var], new_var)
                    bb.insert_instruction(new_inst, idx)
                    use_inst.operands[i] = new_var

from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import IRPass


class StoreExpansionPass(IRPass):
    """
    This pass expands variables to their uses though `store` instructions,
    reducing pressure on the stack scheduler
    """

    def run_pass(self):
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_bb(self, bb):
        i = 0
        while i < len(bb.instructions):
            inst = bb.instructions[i]
            if inst.opcode in ("store", "offset", "phi"):
                i += 1
                continue

            index = i
            for j, op in enumerate(inst.operands):
                if isinstance(op, IRVariable):
                    var = self.function.get_next_variable()
                    to_insert = IRInstruction("store", [op], var)
                    bb.insert_instruction(to_insert, index=index)
                    i += 1
                    inst.operands[j] = var
            i += 1

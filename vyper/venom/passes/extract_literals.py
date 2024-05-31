from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass


class ExtractLiteralsPass(IRPass):
    """
    This pass extracts literals so that they can be reordered by the DFT pass
    """

    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_bb(self, bb):
        i = 0
        while i < len(bb.instructions):
            inst = bb.instructions[i]
            if inst.opcode == "store":
                i += 1
                continue

            for j, op in enumerate(inst.operands):
                # first operand to log is magic
                if inst.opcode == "log" and j == 0:
                    continue

                if isinstance(op, IRLiteral):
                    var = self.function.get_next_variable()
                    to_insert = IRInstruction("store", [op], var)
                    bb.insert_instruction(to_insert, index=i)
                    inst.operands[j] = var
            i += 1

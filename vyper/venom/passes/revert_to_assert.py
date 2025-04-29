from vyper.venom.analysis import CFGAnalysis, DFGAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass

# convert:
# - jnz cond revert_block else to assert (iszero cond); jmp else
# - jnz cond then revert_block to assert cond; jmp then


class RevertToAssert(IRPass):
    cfg: CFGAnalysis

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        fn = self.function

        for bb in fn.get_basic_blocks():
            if len(bb.instructions) != 1:
                continue
            term = bb.instructions[0]
            if term.opcode != "revert" or any(op != IRLiteral(0) for op in term.operands):
                continue

            for pred in self.cfg.cfg_in(bb):
                if pred.instructions[-1].opcode != "jnz":
                    continue

                self._rewrite_jnz(pred, bb)

        self.analyses_cache.invalidate_analysis(CFGAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _rewrite_jnz(self, pred, revert_bb):
        term = pred.instructions[-1]
        cond, then_label, else_label = term.operands
        if then_label == revert_bb.label:
            new_cond = self.function.get_next_variable()
            iszero_inst = IRInstruction("iszero", [cond], output=new_cond)
            assert_inst = IRInstruction("assert", [iszero_inst.output])
            pred.insert_instruction(iszero_inst, index=-1)
            pred.insert_instruction(assert_inst, index=-1)
            # rewrite the jnz into a jmp
            term.opcode = "jmp"
            term.operands = [else_label]
            return

        if else_label == revert_bb.label:
            assert_inst = IRInstruction("assert", [cond])
            pred.insert_instruction(assert_inst, index=-1)
            term.opcode = "jmp"
            term.operands = [then_label]
            return

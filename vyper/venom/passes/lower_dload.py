from vyper.utils import MemoryPositions
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral
from vyper.venom.passes.base_pass import IRPass


class LowerDloadPass(IRPass):
    """
    Lower dload and dloadbytes instructions
    """

    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _handle_bb(self, bb: IRBasicBlock):
        fn = bb.parent
        for idx, inst in enumerate(bb.instructions):
            if inst.opcode == "dload":
                (ptr,) = inst.operands
                var = fn.get_next_variable()
                bb.insert_instruction(
                    IRInstruction("add", [ptr, IRLabel("code_end")], output=var), index=idx
                )
                idx += 1
                dst = IRLiteral(MemoryPositions.FREE_VAR_SPACE)
                bb.insert_instruction(
                    IRInstruction("codecopy", [IRLiteral(32), var, dst]), index=idx
                )

                inst.opcode = "mload"
                inst.operands = [dst]
            elif inst.opcode == "dloadbytes":
                _, src, _ = inst.operands
                code_ptr = fn.get_next_variable()
                bb.insert_instruction(
                    IRInstruction("add", [src, IRLabel("code_end")], output=code_ptr), index=idx
                )
                inst.opcode = "codecopy"
                inst.operands[1] = code_ptr

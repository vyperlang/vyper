from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class LowerDloadPass(IRPass):
    """
    Lower dload and dloadbytes instructions
    """

    # Run after MemMergePass so `dload` patterns are still available for merge opportunities.
    required_predecessors = ("MemMergePass",)

    def run_pass(self):
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(dfg)
        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)

    def _handle_bb(self, bb: IRBasicBlock):
        fn = bb.parent
        for idx, inst in enumerate(bb.instructions):
            if inst.opcode == "dload":
                (ptr,) = inst.operands
                var = fn.get_next_variable()
                tmp_memory = self.updater.add_before(inst, "alloca", [IRLiteral(32)])
                assert tmp_memory is not None
                idx += 1

                bb.insert_instruction(
                    IRInstruction("add", [ptr, IRLabel("code_end")], [var]), index=idx
                )
                idx += 1
                dst = tmp_memory
                bb.insert_instruction(
                    IRInstruction("codecopy", [IRLiteral(32), var, dst]), index=idx
                )

                inst.opcode = "mload"
                inst.operands = [dst]
            elif inst.opcode == "dloadbytes":
                _, src, _ = inst.operands
                code_ptr = fn.get_next_variable()
                bb.insert_instruction(
                    IRInstruction("add", [src, IRLabel("code_end")], [code_ptr]), index=idx
                )
                inst.opcode = "codecopy"
                inst.operands[1] = code_ptr

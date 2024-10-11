from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import CFG_ALTERING_INSTRUCTIONS


class CFGAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    def analyze(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            bb.cfg_in = OrderedSet()
            bb.cfg_out = OrderedSet()
            bb.out_vars = OrderedSet()

        for bb in fn.get_basic_blocks():
            assert len(bb.instructions) > 0, "Basic block should not be empty"
            last_inst = bb.instructions[-1]
            assert last_inst.is_bb_terminator, f"Last instruction should be a terminator {bb}"

            for inst in bb.instructions:
                if inst.opcode in CFG_ALTERING_INSTRUCTIONS:
                    ops = inst.get_label_operands()
                    for op in ops:
                        fn.get_basic_block(op.value).add_cfg_in(bb)

        # Fill in the "out" set for each basic block
        for bb in fn.get_basic_blocks():
            for in_bb in bb.cfg_in:
                in_bb.add_cfg_out(bb)

    def invalidate(self):
        from vyper.venom.analysis.dominators import DominatorTreeAnalysis
        from vyper.venom.analysis.liveness import LivenessAnalysis

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

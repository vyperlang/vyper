from vyper.utils import OrderedSet
from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import CFG_ALTERING_INSTRUCTIONS


class CFGAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    def analyze(self) -> None:
        self._topsort = None

        fn = self.function
        for bb in fn.get_basic_blocks():
            bb.cfg_in = OrderedSet()
            bb.cfg_out = OrderedSet()
            bb.out_vars = OrderedSet()

        for bb in fn.get_basic_blocks():
            assert len(bb.instructions) > 0, "Basic block should not be empty"
            terminator = bb.instructions[-1]
            assert terminator.is_bb_terminator, f"Last instruction should be a terminator {bb}"

            if terminator.opcode in CFG_ALTERING_INSTRUCTIONS:
                ops = terminator.get_label_operands()
                for op in ops:
                    next_bb = fn.get_basic_block(op.value)
                    next_bb.add_cfg_in(bb)
                    bb.add_cfg_out(next_bb)


    def topsort(self):
        if self._topsort is None:
            self._topsort = OrderedSet()
            self._topsort_r(self.function.entry)

        return iter(self._topsort)

    def _topsort_r(self, bb):
        if bb in self._topsort:
            return
        self._topsort.add(bb)

        for next_bb in bb.cfg_out:
            self._topsort_r(next_bb)

    def invalidate(self):
        from vyper.venom.analysis import DominatorTreeAnalysis, LivenessAnalysis

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

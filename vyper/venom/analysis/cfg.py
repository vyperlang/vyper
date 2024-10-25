from typing import Iterator, Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import CFG_ALTERING_INSTRUCTIONS, IRBasicBlock


class CFGAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    _dfs: Optional[list[IRBasicBlock]] = None
    _topsort: Optional[OrderedSet[IRBasicBlock]] = None

    def analyze(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            bb.cfg_in = OrderedSet()
            bb.cfg_out = OrderedSet()
            bb.out_vars = OrderedSet()

        for bb in fn.get_basic_blocks():
            assert bb.is_terminated

            for inst in bb.instructions:
                if inst.opcode in CFG_ALTERING_INSTRUCTIONS:
                    ops = inst.get_label_operands()
                    for op in ops:
                        fn.get_basic_block(op.value).add_cfg_in(bb)

        # Fill in the "out" set for each basic block
        for bb in fn.get_basic_blocks():
            for in_bb in bb.cfg_in:
                in_bb.add_cfg_out(bb)

    def _compute_dfs_r(self, bb=None):
        self._dfs = []

        if bb is None:
            bb = self.function.entry

        self._dfs.append(bb)
        for out_bb in bb.cfg_out:
            self._compute_dfs_r(out_bb)

    def dfs(self) -> Iterator[IRBasicBlock]:
        if self._dfs is None:
            self._compute_dfs_r()

        assert self._dfs is not None  # help mypy
        return iter(self._dfs)

    def topsort(self) -> Iterator[IRBasicBlock]:
        if self._topsort is None:
            self._topsort = OrderedSet(self.dfs())
        return iter(self._topsort)

    def invalidate(self):
        from vyper.venom.analysis import DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

        self._dfs = None
        self._topsort = None

        # be conservative - assume cfg invalidation invalidates dfg
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

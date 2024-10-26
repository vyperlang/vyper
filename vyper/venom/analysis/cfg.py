from typing import Iterator, Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import CFG_ALTERING_INSTRUCTIONS, IRBasicBlock


class CFGAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    _dfs: Optional[OrderedSet[IRBasicBlock]] = None

    def analyze(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            bb.cfg_in = OrderedSet()
            bb.cfg_out = OrderedSet()
            bb.out_vars = OrderedSet()

        for bb in fn.get_basic_blocks():
            assert bb.is_terminated

            term = bb.instructions[-1]
            if term.opcode in CFG_ALTERING_INSTRUCTIONS:
                ops = term.get_label_operands()
                for op in ops:
                    next_bb = fn.get_basic_block(op.value)
                    next_bb.add_cfg_in(bb)
                    bb.add_cfg_out(next_bb)

    def _compute_dfs_r(self, bb, visited=None):
        assert self._dfs is not None  # help mypy
        if visited is None:
            visited = OrderedSet()

        if bb in visited:
            return

        visited.add(bb)

        for out_bb in bb.cfg_out:
            self._compute_dfs_r(out_bb, visited)

        self._dfs.add(bb)

    @property
    def dfs_walk(self) -> Iterator[IRBasicBlock]:
        if self._dfs is None:
            self._dfs = OrderedSet()
            self._compute_dfs_r(self.function.entry)

        assert self._dfs is not None  # help mypy
        return iter(self._dfs)

    def invalidate(self):
        from vyper.venom.analysis import DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

        self._dfs = None

        # be conservative - assume cfg invalidation invalidates dfg
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

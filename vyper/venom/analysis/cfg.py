from typing import Iterator

from vyper.utils import OrderedSet
from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import CFG_ALTERING_INSTRUCTIONS, IRBasicBlock


class CFGAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    _dfs: OrderedSet[IRBasicBlock]

    def analyze(self) -> None:
        fn = self.function
        self._dfs = OrderedSet()

        for bb in fn.get_basic_blocks():
            bb.cfg_in = OrderedSet()
            bb.cfg_out = OrderedSet()
            bb.out_vars = OrderedSet()
            bb.is_reachable = False

        for bb in fn.get_basic_blocks():
            assert bb.is_terminated, f"not terminating:\n{bb}"

            term = bb.instructions[-1]
            if term.opcode in CFG_ALTERING_INSTRUCTIONS:
                ops = term.get_label_operands()
                # order of cfg_out matters to performance!
                for op in reversed(list(ops)):
                    next_bb = fn.get_basic_block(op.value)
                    bb.add_cfg_out(next_bb)
                    next_bb.add_cfg_in(bb)

        self._compute_dfs_post_r(self.function.entry)

    def _compute_dfs_post_r(self, bb):
        if bb.is_reachable:
            return
        bb.is_reachable = True

        for out_bb in bb.cfg_out:
            self._compute_dfs_post_r(out_bb)

        self._dfs.add(bb)

    @property
    def dfs_pre_walk(self) -> Iterator[IRBasicBlock]:
        visited: OrderedSet[IRBasicBlock] = OrderedSet()

        def _visit_dfs_pre_r(bb: IRBasicBlock):
            if bb in visited:
                return
            visited.add(bb)

            yield bb

            for out_bb in bb.cfg_out:
                yield from _visit_dfs_pre_r(out_bb)

        yield from _visit_dfs_pre_r(self.function.entry)

    @property
    def dfs_post_walk(self) -> Iterator[IRBasicBlock]:
        return iter(self._dfs)

    def invalidate(self):
        from vyper.venom.analysis import DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis

        fn = self.function
        for bb in fn.get_basic_blocks():
            bb.cfg_in = OrderedSet()
            bb.cfg_out = OrderedSet()
            bb.out_vars = OrderedSet()

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self._dfs = None

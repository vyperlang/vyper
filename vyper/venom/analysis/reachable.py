from collections import defaultdict

from vyper.utils import OrderedSet
from vyper.venom.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock


class ReachableAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    reachable: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]

    def analyze(self) -> None:
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.reachable = defaultdict(OrderedSet)

        self._compute_reachable_r(self.function.entry)

    def _compute_reachable_r(self, bb):
        if bb in self.reachable:
            return

        s = bb.cfg_out.copy()
        self.reachable[bb] = s

        for out_bb in bb.cfg_out:
            self._compute_reachable_r(out_bb)
            s.update(self.reachable[out_bb])

    def invalidate(self):
        from vyper.venom.analysis import DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

        self._dfs = None

        # be conservative - assume cfg invalidation invalidates dfg
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

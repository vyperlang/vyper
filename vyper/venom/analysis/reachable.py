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
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.reachable = defaultdict(OrderedSet)

        self._compute_reachable_r(self.function.entry)

    def _compute_reachable_r(self, bb):
        if bb in self.reachable:
            return

        s = self.cfg.cfg_out(bb).copy()
        self.reachable[bb] = s

        for out_bb in self.cfg.cfg_out(bb):
            self._compute_reachable_r(out_bb)
            s.update(self.reachable[out_bb])

    def invalidate(self):
        del self.reachable

from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock


class NaturalLoopDetectionAnalysis(IRAnalysis):
    """
    Detects loops and computes basic blocks
    and the block which is before the loop
    """

    # key = start of the loop (last bb not in the loop)
    # value = all the block that loop contains
    loops: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]

    done: OrderedSet[IRBasicBlock]
    visited: OrderedSet[IRBasicBlock]

    def analyze(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.loops: dict[IRBasicBlock, OrderedSet[IRBasicBlock]] = dict()
        self.done = OrderedSet()
        self.visited = OrderedSet()
        entry = self.function.entry
        self._dfs_r(entry)

    def _dfs_r(self, bb: IRBasicBlock, before: IRBasicBlock | None = None):
        if bb in self.visited:
            self.done.add(bb)
            if before is None:
                return
            loop = self._collect_loop_bbs(before, bb)
            in_bb = bb.cfg_in.difference({before})
            if len(in_bb) != 1:
                return
            input_bb = in_bb.first()
            self.loops[input_bb] = loop
            return

        self.visited.add(bb)

        for neighbour in bb.cfg_out:
            if neighbour not in self.done:
                self._dfs_r(neighbour, bb)

        self.done.add(bb)

    def _collect_loop_bbs(
        self, bb_from: IRBasicBlock, bb_to: IRBasicBlock
    ) -> OrderedSet[IRBasicBlock]:
        loop: OrderedSet[IRBasicBlock] = OrderedSet()
        collect_visit: OrderedSet[IRBasicBlock] = OrderedSet()
        self._collect_loop_bbs_r(bb_from, bb_to, loop, collect_visit)
        return loop

    def _collect_loop_bbs_r(
        self,
        curr_bb: IRBasicBlock,
        bb_to: IRBasicBlock,
        loop: OrderedSet[IRBasicBlock],
        visit: OrderedSet[IRBasicBlock],
    ):
        if curr_bb in visit:
            return
        visit.add(curr_bb)
        loop.add(curr_bb)
        if curr_bb == bb_to:
            return

        for before in curr_bb.cfg_in:
            self._collect_loop_bbs_r(before, bb_to, loop, visit)

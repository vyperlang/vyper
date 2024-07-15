from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock


class LoopDetectionAnalysis(IRAnalysis):
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
        self.dfs(entry)

    def invalidate(self):
        return super().invalidate()

    def dfs(self, bb: IRBasicBlock, before : IRBasicBlock = None):
        if bb in self.visited:
            assert before is not None, "Loop must have one basic block before it"
            loop = self.collect_path(before, bb)
            in_bb = bb.cfg_in.difference({before})
            assert len(in_bb) == 1, "Loop must have one input basic block"
            input_bb = in_bb.first()
            self.loops[input_bb] = loop
            self.done.add(bb)
            return

        self.visited.add(bb)

        for neighbour in bb.cfg_out:
            if neighbour not in self.done:
                self.dfs(neighbour, bb)

        self.done.add(bb)
        return
    
    def collect_path(self, bb_from : IRBasicBlock, bb_to: IRBasicBlock) -> OrderedSet[IRBasicBlock]:
        loop = OrderedSet()
        collect_visit = OrderedSet()
        self.collect_path_inner(bb_from, bb_to, loop, collect_visit)
        return loop

    def collect_path_inner(self, act_bb : IRBasicBlock, bb_to: IRBasicBlock, loop : OrderedSet[IRBasicBlock], collect_visit : OrderedSet[IRBasicBlock]):
        if act_bb in collect_visit:
            return
        collect_visit.add(act_bb)
        loop.add(act_bb)
        if act_bb == bb_to:
            return
        
        for before in act_bb.cfg_in:
            self.collect_path_inner(before, bb_to, loop, collect_visit)

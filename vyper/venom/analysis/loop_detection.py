from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock


class LoopDetectionAnalysis(IRAnalysis):
    """
    Detects loops and computes basic blocks sets
    which comprised these loops
    """

    # key = start of the loop (last bb not in the loop), value all the block that loop contains
    loops: dict[IRBasicBlock, list[IRBasicBlock]]

    def analyze(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.loops: dict[IRBasicBlock, list[IRBasicBlock]] = dict()
        done = OrderedSet()
        entry = self.function.entry
        self.dfs(entry, done, [])

    def invalidate(self):
        return super().invalidate()

    def dfs(self, bb: IRBasicBlock, done: OrderedSet[IRBasicBlock], path: list[IRBasicBlock]):
        if bb in path:
            index = path.index(bb)
            assert index >= 1, "Loop must have one basic block before it"
            assert (
                path[index - 1] not in self.loops.keys()
            ), "From one basic block can start only one loop"
            done.add(bb)
            self.loops[path[index - 1]] = path[index:].copy()
            return

        path.append(bb)
        for neighbour in bb.cfg_out:
            if neighbour not in done:
                self.dfs(neighbour, done, path)
        path.pop()

        done.add(bb)
        return

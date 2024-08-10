from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock


class NaturalLoopDetectionAnalysis(IRAnalysis):
    """
    Detects loops and computes basic blocks
    and the block which is before the loop
    """

    # key = loop header
    # value = all the blocks that the loop contains
    loops: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]

    def analyze(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.loops = self._find_natural_loops(self.function.entry)        

    # Could possibly reuse the dominator tree algorithm to find the back edges
    # if it is already cached it will be faster. Still might need to separate the
    # varius extra information that the dominator analysis provides 
    # (like frontiers and immediate dominators)
    def _find_back_edges(self, entry: IRBasicBlock) -> list[tuple[IRBasicBlock, IRBasicBlock]]:
        back_edges = []
        visited = OrderedSet()
        stack = []

        def dfs(bb: IRBasicBlock):
            visited.add(bb)
            stack.append(bb)

            for succ in bb.cfg_out:
                if succ not in visited:
                    dfs(succ)
                elif succ in stack:
                    back_edges.append((bb, succ))

            stack.pop()

        dfs(entry)

        return back_edges
    
    def _find_natural_loops(self, entry: IRBasicBlock) -> dict[IRBasicBlock, OrderedSet[IRBasicBlock]]:
        back_edges = self._find_back_edges(entry)
        natural_loops = {}

        for u, v in back_edges:
            # back edge: u -> v
            loop = OrderedSet()
            stack = [u]

            while stack:
                bb = stack.pop()
                if bb in loop:
                    continue
                loop.add(bb)
                for pred in bb.cfg_in:
                    if pred != v:
                        stack.append(pred)

            loop.add(v)
            natural_loops[v.cfg_in.first()] = loop

        return natural_loops


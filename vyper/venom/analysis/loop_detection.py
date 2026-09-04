from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis import CFGAnalysis, DominatorTreeAnalysis
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
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self._find_loops()
    
    def _find_loops(self):
        self.loops = dict()

        for bb in self.function.get_basic_blocks():
            for succ in self.cfg.cfg_out(bb):
                if not self.dom.dominates(succ, bb):
                    continue

                header = succ
                bbs = self._collect(bb, header)
                if header not in self.loops:
                    self.loops[header] = OrderedSet()
                self.loops[header].addmany(bbs)

        for header in self.loops.copy():
            pre = self.get_pre_header(header)
            if pre is None:
                del self.loops[header]

    def get_pre_header(self, header: IRBasicBlock) -> IRBasicBlock | None:
        preds = self.cfg.cfg_in(header).copy()
        preds.dropmany(self.loops[header])
        if len(preds) != 1:
            return None
        return preds.first()


    def _collect(self, start: IRBasicBlock, header: IRBasicBlock) -> OrderedSet[IRBasicBlock]:
        nodes = OrderedSet()

        def dfs(bb: IRBasicBlock):
            if bb in nodes:
                return
            nodes.add(bb)

            if bb is header:
                return

            for pred in self.cfg.cfg_in(bb):
                dfs(pred)
        
        dfs(start)

        return nodes


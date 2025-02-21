from functools import cached_property

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.function import IRFunction


class DominatorTreeAnalysis(IRAnalysis):
    """
    Dominator tree implementation. This class computes the dominator tree of a
    function and provides methods to query the tree. The tree is computed using
    the Lengauer-Tarjan algorithm.
    """

    fn: IRFunction
    entry_block: IRBasicBlock
    dominators: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    immediate_dominators: dict[IRBasicBlock, IRBasicBlock]
    dominated: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    dominator_frontiers: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]

    def analyze(self):
        """
        Compute the dominator tree.
        """
        self.fn = self.function
        self.entry_block = self.fn.entry
        self.dominators = {}
        self.immediate_dominators = {}
        self.dominated = {}
        self.dominator_frontiers = {}

        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        self._compute_dominators()
        self._compute_idoms()
        self._compute_df()

    def dominates(self, bb1, bb2):
        """
        Check if bb1 dominates bb2.
        """
        return bb2 in self.dominators[bb1]

    def immediate_dominator(self, bb):
        """
        Return the immediate dominator of a basic block.
        """
        return self.immediate_dominators.get(bb)

    def _compute_dominators(self):
        """
        Compute dominators
        """
        basic_blocks = list(self.dfs_post_order.keys())
        self.dominators = {bb: OrderedSet(basic_blocks) for bb in basic_blocks}
        self.dominators[self.entry_block] = OrderedSet([self.entry_block])
        changed = True
        count = len(basic_blocks) ** 2  # TODO: find a proper bound for this
        while changed:
            count -= 1
            if count < 0:
                raise CompilerPanic("Dominators computation failed to converge")
            changed = False
            for bb in basic_blocks:
                if bb == self.entry_block:
                    continue
                preds = bb.cfg_in
                if len(preds) == 0:
                    continue
                new_dominators = OrderedSet.intersection(*[self.dominators[pred] for pred in preds])
                new_dominators.add(bb)
                if new_dominators != self.dominators[bb]:
                    self.dominators[bb] = new_dominators
                    changed = True

    def _compute_idoms(self):
        """
        Compute immediate dominators
        """
        self.immediate_dominators = {bb: None for bb in self.dfs_post_order.keys()}
        self.immediate_dominators[self.entry_block] = self.entry_block
        for bb in self.dfs_post_walk:
            if bb == self.entry_block:
                continue
            doms = sorted(self.dominators[bb], key=lambda x: self.dfs_post_order[x])
            self.immediate_dominators[bb] = doms[1]

        self.dominated = {bb: OrderedSet() for bb in self.dfs_post_walk}
        for dom, target in self.immediate_dominators.items():
            self.dominated[target].add(dom)

    def _compute_df(self):
        """
        Compute dominance frontier
        """
        basic_blocks = self.dfs_post_walk
        self.dominator_frontiers = {bb: OrderedSet() for bb in basic_blocks}

        for bb in self.dfs_post_walk:
            if len(bb.cfg_in) > 1:
                for pred in bb.cfg_in:
                    runner = pred
                    while runner != self.immediate_dominators[bb]:
                        self.dominator_frontiers[runner].add(bb)
                        runner = self.immediate_dominators[runner]

    def dominance_frontier(self, basic_blocks: list[IRBasicBlock]) -> OrderedSet[IRBasicBlock]:
        """
        Compute dominance frontier of a set of basic blocks.
        """
        df = OrderedSet[IRBasicBlock]()
        for bb in basic_blocks:
            df.update(self.dominator_frontiers[bb])
        return df

    def _intersect(self, bb1, bb2):
        """
        Find the nearest common dominator of two basic blocks.
        """
        dfs_order = self.dfs_order
        while bb1 != bb2:
            while dfs_order[bb1] < dfs_order[bb2]:
                bb1 = self.immediate_dominators[bb1]
            while dfs_order[bb1] > dfs_order[bb2]:
                bb2 = self.immediate_dominators[bb2]
        return bb1

    @cached_property
    def dfs_post_walk(self) -> list[IRBasicBlock]:
        return list(self.cfg.dfs_post_walk)

    @cached_property
    def dfs_post_order(self) -> dict[IRBasicBlock, int]:
        return {bb: idx for idx, bb in enumerate(self.dfs_post_walk)}

    def as_graph(self) -> str:
        """
        Generate a graphviz representation of the dominator tree.
        """
        lines = ["digraph dominator_tree {"]
        for bb in self.fn.get_basic_blocks():
            if bb == self.entry_block:
                continue
            idom = self.immediate_dominator(bb)
            if idom is None:
                continue
            lines.append(f'    " {idom.label} " -> " {bb.label} "')
        lines.append("}")
        return "\n".join(lines)

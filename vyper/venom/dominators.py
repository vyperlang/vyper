from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.function import IRFunction


class DominatorTree:
    """
    Dominator tree.
    """

    ctx: IRFunction
    entry: IRBasicBlock
    dfs_order: dict[IRBasicBlock, int]
    dfs: list[IRBasicBlock]
    dominators: dict[IRBasicBlock, set[IRBasicBlock]]
    idoms: dict[IRBasicBlock, IRBasicBlock]
    dominated: dict[IRBasicBlock, set[IRBasicBlock]]
    df: dict[IRBasicBlock, set[IRBasicBlock]]

    def __init__(self, ctx: IRFunction, entry: IRBasicBlock):
        self.ctx = ctx
        self.entry = entry
        self.dfs_order = {}
        self.dfs = []
        self.dominators = {}
        self.idoms = {}
        self.dominated = {}
        self.df = {}
        self._compute()

    def dominates(self, bb1, bb2):
        return bb2 in self.dominators[bb1]

    def immediate_dominator(self, bb):
        return self.idoms.get(bb)

    def _compute(self):
        self._dfs(self.entry, set())
        self._compute_dominators()
        self._compute_idoms()
        self._compute_df()

    def _compute_dominators(self):
        basic_blocks = list(self.dfs_order.keys())
        self.dominators = {bb: set(basic_blocks) for bb in basic_blocks}
        self.dominators[self.entry] = {self.entry}
        changed = True
        count = len(basic_blocks) ** 2  # TODO: find a proper bound for this
        while changed:
            count -= 1
            if count < 0:
                raise CompilerPanic("Dominators computation failed to converge")
            changed = False
            for bb in basic_blocks:
                if bb == self.entry:
                    continue
                preds = bb.cfg_in
                if len(preds) > 0:
                    new_dominators = set.intersection(*[self.dominators[pred] for pred in preds])
                new_dominators.add(bb)
                if new_dominators != self.dominators[bb]:
                    self.dominators[bb] = new_dominators
                    changed = True

        # for bb in basic_blocks:
        #     print(bb.label)
        #     for dom in self.dominators[bb]:
        #         print("    ", dom.label)

    def _compute_idoms(self):
        """
        Compute immediate dominators
        """
        self.idoms = {bb: None for bb in self.dfs_order.keys()}
        self.idoms[self.entry] = self.entry
        for bb in self.dfs:
            if bb == self.entry:
                continue
            doms = sorted(self.dominators[bb], key=lambda x: self.dfs_order[x])
            self.idoms[bb] = doms[1]

        self.dominated = {bb: set() for bb in self.dfs}
        for dom, target in self.idoms.items():
            self.dominated[target].add(dom)

        # for dom, targets in self.dominated.items():
        #     print(dom.label)
        #     for t in targets:
        #         print("    ", t.label)

    def _compute_df(self):
        """
        Compute dominance frontier
        """
        basic_blocks = self.dfs
        self.df = {bb: set() for bb in basic_blocks}

        for bb in self.dfs:
            if len(bb.cfg_in) > 1:
                for pred in bb.cfg_in:
                    runner = pred
                    while runner != self.idoms[bb]:
                        self.df[runner].add(bb)
                        runner = self.idoms[runner]

        # for bb in self.dfs:
        #     print(bb.label)
        #     for df in self.df[bb]:
        #         print("    ", df.label)

    def dominance_frontier(self, basic_blocks: list[IRBasicBlock]):
        """
        Compute dominance frontier of a set of basic blocks.
        """
        df = set()
        for bb in basic_blocks:
            df.update(self.df[bb])
        return df

    def _intersect(self, bb1, bb2):
        dfs_order = self.dfs_order
        while bb1 != bb2:
            while dfs_order[bb1] < dfs_order[bb2]:
                bb1 = self.idoms[bb1]
            while dfs_order[bb1] > dfs_order[bb2]:
                bb2 = self.idoms[bb2]
        return bb1

    def _dfs(self, entry: IRBasicBlock, visited):
        visited.add(entry)

        for bb in entry.cfg_out:
            if bb not in visited:
                self._dfs(bb, visited)

        self.dfs.append(entry)
        self.dfs_order[entry] = len(self.dfs)

    def as_graph(self) -> str:
        """
        Generate a graphviz representation of the dominator tree.
        """
        lines = ["digraph dominator_tree {"]
        for bb in self.ctx.basic_blocks:
            if bb == self.entry:
                continue
            idom = self.immediate_dominator(bb)
            if idom is None:
                continue
            lines.append(f'    "{idom.label}" -> "{bb.label}"')
        lines.append("}")
        return "\n".join(lines)

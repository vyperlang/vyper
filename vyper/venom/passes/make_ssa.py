from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    dom: DominatorTree
    defs: dict[IRVariable, set[IRBasicBlock]]

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        entry = ctx.get_basic_block(ctx.entry_points[0].value)
        dom = DominatorTree(ctx, entry)
        self.dom = dom

        self._compute_defs()
        self._add_phi_nodes()
        # self._dfs_dom(entry, set())

        print(ctx.as_graph())

        self.changes = 0

    def _add_phi_nodes(self):
        for var, defs in self.defs.items():
            for bb in defs:
                for front in self.dom.df[bb]:
                    self._add_phi(var, front)

    def _dfs_dom(self, basic_block: IRBasicBlock, visited: set):
        visited.add(basic_block)
        for bb in self.dom.dominated[basic_block]:
            if bb not in visited:
                self._dfs_dom(bb, visited)

        self._process_basic_block(basic_block)

    def _add_phi(self, var: IRVariable, basic_block: IRBasicBlock):
        # TODO: check if the phi already exists
        args = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue
            args.append(var)
            args.append(bb.label)
        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

    def _compute_defs(self):
        self.defs = {}
        for bb in self.dom.dfs:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in self.defs:
                    self.defs[var] = set()
                self.defs[var].add(bb)

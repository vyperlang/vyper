from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    dom: DominatorTree

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        entry = ctx.get_basic_block(ctx.entry_points[0].value)
        dom = DominatorTree(ctx, entry)
        self.dom = dom

        # self._dfs_dom(entry, set())

        print(ctx.as_graph())

        self.changes = 0

    def _dfs_dom(self, basic_block: IRBasicBlock, visited: set):
        visited.add(basic_block)
        for bb in self.dom.dominated[basic_block]:
            if bb not in visited:
                self._dfs_dom(bb, visited)

        self._process_basic_block(basic_block)

    def _process_basic_block(self, basic_block: IRBasicBlock):
        defs = {}
        assignments = basic_block.get_assignments()
        for var in assignments:
            if var not in defs:
                defs[var] = set()
            defs[var].add(basic_block)

        for var, d in defs.items():
            df = self.dom.dominance_frontier(d)
            for bb in df:
                self._add_phi(var, bb)

    def _add_phi(self, var: IRVariable, basic_block: IRBasicBlock):
        args = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue
            args.append(var)
            args.append(bb.label)
        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

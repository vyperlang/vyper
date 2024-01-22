from vyper.venom.analysis import calculate_cfg
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        entry = ctx.get_basic_block(ctx.entry_points[0].value)
        dom = DominatorTree(ctx, entry)

        self.changes = 0

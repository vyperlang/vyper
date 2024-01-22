from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        entry = ctx.get_basic_block(ctx.entry_points[0].value)
        dom = DominatorTree(ctx, entry)

        defs = {}
        for bb in ctx.basic_blocks:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in defs:
                    defs[var] = set()
                defs[var].add(bb)

        for var, d in defs.items():
            df = dom.dominance_frontier(d)
            for bb in df:
                self._add_phi(var, bb)

        self.changes = 0

    def _add_phi(self, var: IRVariable, basic_block: IRBasicBlock):
        args = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue
            args.append(var)
            args.append(bb.label)
        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

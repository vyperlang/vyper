from vyper.utils import OrderedSet
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class SimplifyCFGPass(IRPass):
    visited: OrderedSet

    def _merge_blocks(self, a: IRBasicBlock, b: IRBasicBlock):
        a.instructions.pop()
        for inst in b.instructions:
            assert inst.opcode != "phi", "Not implemented yet"
            if inst.opcode == "phi":
                a.instructions.insert(0, inst)
            else:
                inst.parent = a
                a.instructions.append(inst)
        a.cfg_out = b.cfg_out

        for n in b.cfg_out:
            n.remove_cfg_in(b)
            n.add_cfg_in(a)

    def _collapse_chained_blocks_r(self, bb: IRBasicBlock):
        if len(bb.cfg_out) == 1:
            next = bb.cfg_out.first()
            if len(next.cfg_in) == 1:
                self._merge_blocks(bb, next)
                self.ctx.basic_blocks.remove(next)
                self._collapse_chained_blocks_r(bb)
                return

        if bb in self.visited:
            return
        self.visited.add(bb)

        for bb_out in bb.cfg_out:
            self._collapse_chained_blocks_r(bb_out)

    def _collapse_chained_blocks(self, entry: IRBasicBlock):
        self.visited = OrderedSet()
        self._collapse_chained_blocks_r(entry)

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> None:
        self.ctx = ctx

        self._collapse_chained_blocks(entry)

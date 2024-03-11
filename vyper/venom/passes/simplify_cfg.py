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

        self.ctx.basic_blocks.remove(b)

    def _merge_jump(self, a: IRBasicBlock, b: IRBasicBlock):
        next = b.cfg_out.first()
        jump_inst = a.instructions[-1]
        assert b.label in jump_inst.operands, f"{b.label} {jump_inst.operands}"
        jump_inst.operands[jump_inst.operands.index(b.label)] = next.label
        a.remove_cfg_out(b)
        a.add_cfg_out(next)
        next.remove_cfg_in(b)
        next.add_cfg_in(a)
        self.ctx.basic_blocks.remove(b)

    def _collapse_chained_blocks_r(self, bb: IRBasicBlock):
        if len(bb.cfg_out) == 1:
            next = bb.cfg_out.first()
            if len(next.cfg_in) == 1:
                self._merge_blocks(bb, next)
                self._collapse_chained_blocks_r(bb)
                return
        elif len(bb.cfg_out) == 2:
            bb_out = bb.cfg_out.copy()
            for next in bb_out:
                if len(next.cfg_in) == 1 and len(next.cfg_out) == 1 and len(next.instructions) == 1:
                    self._merge_jump(bb, next)
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

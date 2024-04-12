from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.bb_optimizer import ir_pass_remove_unreachable_blocks
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

        # Update CFG
        a.cfg_out = b.cfg_out
        if len(b.cfg_out) > 0:
            next_bb = b.cfg_out.first()
            next_bb.remove_cfg_in(b)
            next_bb.add_cfg_in(a)

            for inst in next_bb.instructions:
                if inst.opcode != "phi":
                    break
                inst.operands[inst.operands.index(b.label)] = a.label

        self.ctx.basic_blocks.remove(b)

    def _merge_jump(self, a: IRBasicBlock, b: IRBasicBlock):
        next_bb = b.cfg_out.first()
        jump_inst = a.instructions[-1]
        assert b.label in jump_inst.operands, f"{b.label} {jump_inst.operands}"
        jump_inst.operands[jump_inst.operands.index(b.label)] = next_bb.label

        # Update CFG
        a.remove_cfg_out(b)
        a.add_cfg_out(next_bb)
        next_bb.remove_cfg_in(b)
        next_bb.add_cfg_in(a)

        self.ctx.basic_blocks.remove(b)

    def _collapse_chained_blocks_r(self, bb: IRBasicBlock):
        """
        DFS into the cfg and collapse blocks with a single predecessor to the predecessor
        """
        if len(bb.cfg_out) == 1:
            next_bb = bb.cfg_out.first()
            if len(next_bb.cfg_in) == 1:
                self._merge_blocks(bb, next_bb)
                self._collapse_chained_blocks_r(bb)
                return
        elif len(bb.cfg_out) == 2:
            bb_out = bb.cfg_out.copy()
            for next_bb in bb_out:
                if (
                    len(next_bb.cfg_in) == 1
                    and len(next_bb.cfg_out) == 1
                    and len(next_bb.instructions) == 1
                ):
                    self._merge_jump(bb, next_bb)
                    self._collapse_chained_blocks_r(bb)
                    return

        if bb in self.visited:
            return
        self.visited.add(bb)

        for bb_out in bb.cfg_out:
            self._collapse_chained_blocks_r(bb_out)

    def _collapse_chained_blocks(self, entry: IRBasicBlock):
        """
        Collapse blocks with a single predecessor to their predecessor
        """
        self.visited = OrderedSet()
        self._collapse_chained_blocks_r(entry)

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> None:
        self.ctx = ctx

        while True:
            self._collapse_chained_blocks(entry)
            if ir_pass_remove_unreachable_blocks(ctx) == 0:
                break

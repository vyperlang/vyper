from vyper.venom.analysis import DFG, calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class Normalization(IRPass):
    """
    This pass splits basic blocks when there are multiple conditional predecessors.
    The code generator expect a normalized CFG, that has the property that
    each basic block has at most one conditional predecessor.
    """

    changes = 0

    def _split_basic_block(self, bb: IRBasicBlock) -> None:
        ctx = self.ctx
        label_base = bb.label.value

        # Iterate over the predecessors of the basic block
        for in_bb in bb.cfg_in:
            jump_inst = in_bb.instructions[-1]
            # We are only splitting on contitional jumps
            if jump_inst.opcode != "jnz":
                continue

            # Create an intermediary basic block and append it
            split_bb = IRBasicBlock(IRLabel(label_base + "_split_" + in_bb.label.value), ctx)
            ctx.append_basic_block(split_bb)
            ctx.append_instruction("jmp", [bb.label], False)

            # Redirect the original conditional jump to the intermediary basic block
            jump_inst.operands[1] = split_bb.label

            self.changes += 1

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx
        self.dfg = DFG.build_dfg(ctx)
        self.changes = 0

        # Calculate control flow graph if needed
        if ctx.cfg_dirty:
            calculate_cfg(ctx)

        for bb in ctx.basic_blocks:
            if len(bb.cfg_in) > 1:
                self._split_basic_block(bb)

        # Recalculate control flow graph
        calculate_cfg(ctx)

        # Sanity check
        assert ctx.normalized is True, "Normalization pass failed"

        return self.changes

from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class NormalizationPass(IRPass):
    """
    This pass splits basic blocks when there are multiple conditional predecessors.
    The code generator expect a normalized CFG, that has the property that
    each basic block has at most one conditional predecessor.
    """

    changes = 0

    def _split_basic_block(self, bb: IRBasicBlock) -> None:
        # Iterate over the predecessors to this basic block
        for in_bb in list(bb.cfg_in):
            assert bb in in_bb.cfg_out
            # Handle branching in the predecessor bb
            if len(in_bb.cfg_out) > 1:
                self._insert_split_basicblock(bb, in_bb)
                self.changes += 1
                break

    def _insert_split_basicblock(self, bb: IRBasicBlock, in_bb: IRBasicBlock) -> IRBasicBlock:
        # Create an intermediary basic block and append it
        source = in_bb.label.value
        target = bb.label.value

        split_label = IRLabel(f"{target}_split_{source}")
        in_terminal = in_bb.instructions[-1]
        in_terminal.replace_label_operands({bb.label: split_label})

        split_bb = IRBasicBlock(split_label, self.ctx)
        split_bb.append_instruction("jmp", bb.label)
        self.ctx.append_basic_block(split_bb)

        # Update the labels in the data segment
        for inst in self.ctx.data_segment:
            if inst.opcode == "db" and inst.operands[0] == bb.label:
                inst.operands[0] = split_bb.label

        return split_bb

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx
        self.changes = 0

        # Split blocks that need splitting
        for bb in ctx.basic_blocks:
            if len(bb.cfg_in) > 1:
                self._split_basic_block(bb)

        # If we made changes, recalculate the cfg
        if self.changes > 0:
            calculate_cfg(ctx)

        return self.changes

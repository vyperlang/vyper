from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
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
        # Iterate over the predecessors of the basic block
        for in_bb in list(bb.cfg_in):
            jump_inst = in_bb.instructions[-1]
            assert bb in in_bb.cfg_out

            # Handle static and dynamic branching
            if jump_inst.opcode == "jnz":
                self._split_for_static_branch(bb, in_bb)
            elif jump_inst.opcode == "jmp" and isinstance(jump_inst.operands[0], IRVariable):
                self._split_for_dynamic_branch(bb, in_bb)
            else:
                continue

            self.changes += 1

    def _split_for_static_branch(self, bb: IRBasicBlock, in_bb: IRBasicBlock) -> None:
        jump_inst = in_bb.instructions[-1]
        for i, op in enumerate(jump_inst.operands):
            if op == bb.label:
                edge = i
                break
        else:
            # none of the edges points to this bb
            raise CompilerPanic("bad CFG")

        assert edge in (1, 2)  # the arguments which can be labels

        split_bb = self._insert_split_basicblock(bb, in_bb)

        # Redirect the original conditional jump to the intermediary basic block
        jump_inst.operands[edge] = split_bb.label

    def _split_for_dynamic_branch(self, bb: IRBasicBlock, in_bb: IRBasicBlock) -> None:
        split_bb = self._insert_split_basicblock(bb, in_bb)

        # Update any affected labels in the data segment
        # TODO: this DESTROYS the cfg! refactor so the translation of the
        # selector table produces indirect jumps properly.
        for inst in self.ctx.data_segment:
            if inst.opcode == "db" and inst.operands[0] == bb.label:
                inst.operands[0] = split_bb.label

    def _insert_split_basicblock(self, bb: IRBasicBlock, in_bb: IRBasicBlock) -> IRBasicBlock:
        # Create an intermediary basic block and append it
        source = in_bb.label.value
        target = bb.label.value
        split_bb = IRBasicBlock(IRLabel(f"{target}_split_{source}"), self.ctx)
        split_bb.append_inst_no_ret("jmp", bb.label)
        self.ctx.append_basic_block(split_bb)

        # Rewire the CFG
        # TODO: this is cursed code, it is necessary instead of just running
        # calculate_cfg() because split_for_dynamic_branch destroys the CFG!
        # ideally, remove this rewiring and just re-run calculate_cfg().
        split_bb.add_cfg_in(in_bb)
        split_bb.add_cfg_out(bb)
        in_bb.remove_cfg_out(bb)
        in_bb.add_cfg_out(split_bb)
        bb.remove_cfg_in(in_bb)
        bb.add_cfg_in(split_bb)
        return split_bb

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx
        self.changes = 0

        for bb in ctx.basic_blocks:
            if len(bb.cfg_in) > 1:
                self._split_basic_block(bb)

        # Sanity check
        assert ctx.normalized, "Normalization pass failed"

        return self.changes

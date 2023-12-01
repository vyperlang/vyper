from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRVariable
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
        ctx = self.ctx

        # Iterate over the predecessors of the basic block
        for in_bb in bb.cfg_in:
            # We are only splitting on conditional jumps
            if len(in_bb.cfg_out) <= 1:
                continue

            jump_inst = in_bb.instructions[-1]
            assert bb in in_bb.cfg_out

            # find which edge of the jnz targets this block
            # jnz condition label1 label2
            if jump_inst.opcode == "jnz":
                self._split_for_static_branch(bb, in_bb)
            elif jump_inst.opcode == "jmp" and isinstance(jump_inst.operands[0], IRVariable):
                self._split_for_dynamic_branch(bb, in_bb)
            else:
                raise CompilerPanic("Unexpected termination instruction during normalization")

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

        # Create an intermediary basic block and append it
        source = in_bb.label.value
        target = bb.label.value
        split_bb = IRBasicBlock(IRLabel(f"{target}_split_{source}"), self.ctx)
        split_bb.append_instruction(IRInstruction("jmp", [bb.label]))

        self.ctx.append_basic_block(split_bb)

        # Redirect the original conditional jump to the intermediary basic block
        jump_inst.operands[edge] = split_bb.label

    def _split_for_dynamic_branch(self, bb: IRBasicBlock, in_bb: IRBasicBlock) -> None:
        pass

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx
        self.changes = 0

        # Ensure that the CFG is up to date
        calculate_cfg(ctx)

        for bb in ctx.basic_blocks:
            if len(bb.cfg_in) > 1:  # and len(bb.cfg_out) > 1:
                self._split_basic_block(bb)

        # Recalculate control flow graph
        # (perf: could do this only when self.changes > 0, but be paranoid)
        calculate_cfg(ctx)

        # Sanity check
        assert ctx.normalized, "Normalization pass failed"

        return self.changes

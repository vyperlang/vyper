from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel
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
            if len(in_bb.cfg_out) < 2:
                continue

            # sanity checks. only jnz can product len(cfg_out) > 1
            jump_inst = in_bb.instructions[-1]
            assert jump_inst.opcode == "jnz"
            # jnz produces cfg_out with length 2
            assert len(in_bb.cfg_out) == 2
            assert bb in in_bb.cfg_out

            # find which edge of the jnz targets this block
            # jnz condition label1 label2
            jump_inst.operands[1] == jump_inst.operands[2]
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
            split_bb = IRBasicBlock(IRLabel(f"{target}_split_{source}"), ctx)
            split_bb.append_instruction(IRInstruction("jmp", [bb.label]))

            ctx.append_basic_block(split_bb)

            # Redirect the original conditional jump to the intermediary basic block
            jump_inst.operands[edge] = split_bb.label

            self.changes += 1

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx
        self.changes = 0

        # Ensure that the CFG is up to date
        calculate_cfg(ctx)

        for bb in ctx.basic_blocks:
            if len(bb.cfg_in) > 1:
                self._split_basic_block(bb)

        # Recalculate control flow graph
        # (perf: could do this only when self.changes > 0, but be paranoid)
        calculate_cfg(ctx)

        # Sanity check
        assert ctx.normalized, "Normalization pass failed"

        return self.changes

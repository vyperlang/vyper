from vyper.exceptions import CompilerPanic
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel
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
        fn = self.function

        split_label = IRLabel(f"{source}_split_{target}")
        in_terminal = in_bb.instructions[-1]
        in_terminal.replace_label_operands({bb.label: split_label})

        split_bb = IRBasicBlock(split_label, fn)
        split_bb.append_instruction("jmp", bb.label)
        fn.append_basic_block(split_bb)

        for inst in bb.instructions:
            if inst.opcode != "phi":
                continue
            for i in range(0, len(inst.operands), 2):
                if inst.operands[i] == in_bb.label:
                    inst.operands[i] = split_bb.label

        # Update the labels in the data segment
        for inst in fn.ctx.data_segment:
            if inst.opcode == "db" and inst.operands[0] == bb.label:
                inst.operands[0] = split_bb.label

        return split_bb

    def _run_pass(self) -> int:
        fn = self.function
        self.changes = 0

        self.analyses_cache.request_analysis(CFGAnalysis)

        # Split blocks that need splitting
        for bb in list(fn.get_basic_blocks()):
            if len(bb.cfg_in) > 1:
                self._split_basic_block(bb)

        # If we made changes, recalculate the cfg
        if self.changes > 0:
            self.analyses_cache.force_analysis(CFGAnalysis)
            fn.remove_unreachable_blocks()

        return self.changes

    def run_pass(self):
        fn = self.function
        for _ in range(fn.num_basic_blocks * 2):
            if self._run_pass() == 0:
                break
        else:
            raise CompilerPanic("Normalization pass did not converge")

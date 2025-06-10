from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class CFGNormalization(IRPass):
    """
    This pass splits basic blocks when there are multiple conditional predecessors.
    The code generator expect a normalized CFG, that has the property that
    each basic block has at most one conditional predecessor.
    """

    cfg: CFGAnalysis

    changes = 0

    def _split_basic_block(self, bb: IRBasicBlock) -> None:
        # iterate over the predecessors to this basic block
        for in_bb in list(self.cfg.cfg_in(bb)):
            assert bb in self.cfg.cfg_out(in_bb)
            # handle branching in the predecessor bb
            if len(self.cfg.cfg_out(in_bb)) > 1:
                self._insert_split_basicblock(bb, in_bb)
                self.changes += 1
                break

    def _insert_split_basicblock(self, bb: IRBasicBlock, in_bb: IRBasicBlock) -> IRBasicBlock:
        # create an intermediary basic block and append it
        fn = self.function

        split_label = IRLabel(f"{in_bb.label.value}_split_{bb.label.value}")
        split_bb = IRBasicBlock(split_label, fn)

        in_terminal = in_bb.instructions[-1]
        in_terminal.replace_label_operands({bb.label: split_label})

        # variables referenced in the phi node from in_bb might be defined either
        # by a phi in in_bb, or in a block that dominates in_bb. these need
        # forwarding through a store instruction in the split block.
        var_replacements = {}
        for inst in bb.instructions:
            if inst.opcode != "phi":
                continue

            for i in range(0, len(inst.operands), 2):
                if inst.operands[i] != in_bb.label:
                    continue

                var = inst.operands[i + 1]
                assert isinstance(var, IRVariable)  # help mypy
                if var in var_replacements:
                    continue

                if self._needs_forwarding_store(var, in_bb):
                    # create a new variable (preserving SSA form) that copies the value
                    new_var = fn.get_next_variable()
                    var_replacements[var] = new_var
                    # this creates: %new_var = %var (a copy, not a redefinition)
                    split_bb.append_instruction("store", var, ret=new_var)

        split_bb.append_instruction("jmp", bb.label)
        fn.append_basic_block(split_bb)

        # update phi nodes in bb to reference split_bb instead of in_bb
        self._update_phi_nodes(bb, in_bb, split_bb, var_replacements)

        # update the labels in the data segment
        self._update_data_segment(fn, bb, split_bb)

        return split_bb

    def _needs_forwarding_store(self, var: IRVariable, pred_bb: IRBasicBlock) -> bool:
        for inst in pred_bb.instructions:
            if inst.output == var:
                # variable defined by phi needs forwarding
                return inst.opcode == "phi"
        # variable not defined in predecessor needs forwarding
        return True

    def _update_phi_nodes(
        self,
        bb: IRBasicBlock,
        old_pred: IRBasicBlock,
        new_pred: IRBasicBlock,
        var_replacements: dict,
    ) -> None:
        for inst in bb.instructions:
            if inst.opcode != "phi":
                continue

            for i in range(0, len(inst.operands), 2):
                if inst.operands[i] == old_pred.label:
                    inst.operands[i] = new_pred.label
                    # update variable if it was forwarded
                    var = inst.operands[i + 1]
                    if var in var_replacements:
                        inst.operands[i + 1] = var_replacements[var]

    def _update_data_segment(
        self, fn: IRFunction, bb: IRBasicBlock, split_bb: IRBasicBlock
    ) -> None:
        for data_section in fn.ctx.data_segment:
            for item in data_section.data_items:
                if item.data == bb.label:
                    item.data = split_bb.label

    def _run_pass(self) -> int:
        fn = self.function
        self.changes = 0

        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        # split blocks that need splitting
        for bb in list(fn.get_basic_blocks()):
            if len(self.cfg.cfg_in(bb)) > 1:
                self._split_basic_block(bb)

        # if we made changes, recalculate the cfg
        if self.changes > 0:
            self.analyses_cache.invalidate_analysis(CFGAnalysis)

        return self.changes

    def run_pass(self):
        fn = self.function
        for _ in range(fn.num_basic_blocks * 2):
            if self._run_pass() == 0:
                break
        else:
            raise CompilerPanic("Normalization pass did not converge")

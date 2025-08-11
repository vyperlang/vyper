from typing import Iterator

from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRVariable
from vyper.venom.passes.base_pass import IRPass


class CFGNormalization(IRPass):
    """
    This pass splits basic blocks when there are multiple conditional predecessors.
    The code generator expect a normalized CFG, that has the property that
    each basic block has at most one conditional predecessor.
    """

    cfg: CFGAnalysis

    changes = 0

    def _get_phi_instructions(self, bb: IRBasicBlock) -> Iterator[IRInstruction]:
        """Get all phi instructions in a basic block."""
        for inst in bb.instructions:
            if inst.opcode != "phi":
                break  # phis are always at the beginning
            yield inst

    def _process_block_predecessors(self, bb: IRBasicBlock) -> None:
        """Check if any predecessors need split blocks inserted."""
        # iterate over the predecessors to this basic block
        for pred_bb in list(self.cfg.cfg_in(bb)):
            assert bb in self.cfg.cfg_out(pred_bb)
            # handle branching in the predecessor bb
            if len(self.cfg.cfg_out(pred_bb)) > 1:
                self._insert_split_basicblock(bb, pred_bb)
                self.changes += 1
                break

    def _insert_split_basicblock(self, bb: IRBasicBlock, pred_bb: IRBasicBlock) -> IRBasicBlock:
        # create an intermediary basic block and append it
        fn = self.function

        split_label = IRLabel(f"{pred_bb.label.value}_split_{bb.label.value}")
        split_bb = IRBasicBlock(split_label, fn)

        pred_terminal = pred_bb.instructions[-1]
        pred_terminal.replace_label_operands({bb.label: split_label})

        # variables referenced in the phi node from pred_bb might be defined
        # either by a phi in pred_bb, or in a block that dominates pred_bb.
        # these need forwarding through a store instruction in the split block.
        var_replacements: dict[IRVariable, IRVariable] = {}
        for inst in self._get_phi_instructions(bb):
            for label, var in inst.phi_operands:
                if label != pred_bb.label:
                    continue

                assert isinstance(var, IRVariable)  # help mypy
                if var in var_replacements:
                    continue

                if self._needs_forwarding_store(var, pred_bb):
                    new_var = split_bb.append_instruction("assign", var)
                    assert new_var is not None  # help mypy
                    var_replacements[var] = new_var

        split_bb.append_instruction("jmp", bb.label)
        fn.append_basic_block(split_bb)

        # update phi nodes in bb to reference split_bb instead of pred_bb
        self._update_phi_nodes(bb, pred_bb, split_bb, var_replacements)

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
        var_replacements: dict[IRVariable, IRVariable],
    ) -> None:
        for inst in self._get_phi_instructions(bb):
            # manually update operands since phi_operands is read-only
            for i in range(0, len(inst.operands), 2):
                if inst.operands[i] == old_pred.label:
                    inst.operands[i] = new_pred.label
                    # update variable if it was forwarded
                    var = inst.operands[i + 1]
                    assert isinstance(var, IRVariable)  # help mypy
                    if var in var_replacements:
                        inst.operands[i + 1] = var_replacements[var]

    def _run_pass(self) -> int:
        fn = self.function
        self.changes = 0

        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        # split blocks that need splitting
        for bb in list(fn.get_basic_blocks()):
            if len(self.cfg.cfg_in(bb)) > 1:
                self._process_block_predecessors(bb)

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

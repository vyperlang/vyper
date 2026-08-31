from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class SingleUseExpansion(IRPass):
    """
    This pass transforms venom IR to "single use" form. It extracts literals
    and variables so that they can be reordered by the DFT pass. It creates
    two invariants:
    - each variable is used at most once (by any opcode besides a simple
      assignment)
    - operands to all instructions (besides assignment instructions) must
      be variables.

    these two properties are helpful for DFT and venom_to_assembly.py, and
    in fact the first invariant is *required* by venom_to_assembly.py.

    This pass is in some sense the "inverse" of AssignElimination.
    """

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_bb(self, bb):
        i = 0
        while i < len(bb.instructions):
            inst = bb.instructions[i]
            if inst.opcode == "phi":
                self._process_phi(inst)
                i += 1
                continue
            if inst.opcode in ("assign", "offset") or inst.is_param:
                i += 1
                continue

            ops = inst.operands.copy()

            for j, op in enumerate(ops):
                # first operand to log is magic
                if inst.opcode == "log" and j == 0:
                    continue

                if isinstance(op, IRVariable):
                    uses = self.dfg.get_uses(op)
                    if len(uses) == 1 and len([x for x in inst.operands if x == op]) == 1:
                        continue

                if not isinstance(op, (IRLiteral, IRVariable)):
                    # IRLabels are special in certain instructions (e.g., jmp)
                    # skip them for now.
                    continue

                var = self.updater.add_before(inst, "assign", [op])
                assert var is not None
                if len(inst.operands) > j:
                    inst.operands[j] = var
                i += 1

            i += 1

    def _process_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi"

        for idx, (label, var) in enumerate(inst.phi_operands):
            assert isinstance(var, IRVariable)

            # problematic case is only when two phis
            # are getting same variable at the start of the
            # same basic block otherwise this is not needed
            uses = self.dfg.get_uses_in_bb(var, inst.parent)
            uses = [use for use in uses if use.opcode != "assign"]
            if len(uses) == 1:
                continue

            source = self.function.get_basic_block(label.name)
            terminator = source.instructions[-1]
            new_var = self.updater.add_before(terminator, "assign", [var])
            assert new_var is not None

            # only update the current var and not
            # more in the case that the variable is used
            # in more edges
            ops = inst.operands.copy()
            ops[2 * idx + 1] = new_var

            self.updater.update(inst, "phi", ops)

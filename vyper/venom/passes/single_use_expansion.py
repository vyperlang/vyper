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
            if inst.opcode in ("assign", "offset", "param"):
                i += 1
                continue

            if inst.opcode == "phi":
                self._process_phi(inst)
                i += 1
                continue

            for j, op in enumerate(inst.operands):
                # first operand to log is magic
                if inst.opcode == "log" and j == 0:
                    continue

                if isinstance(op, IRVariable):
                    uses = self.dfg.get_uses(op)
                    # it's already only used once
                    if len(uses) == 1 and len([x for x in inst.operands if x == op]) == 1:
                        continue

                if not isinstance(op, (IRLiteral, IRVariable)):
                    # IRLabels are special in certain instructions (e.g., jmp)
                    # skip them for now.
                    continue

                var = self.function.get_next_variable()
                to_insert = IRInstruction("assign", [op], var)
                bb.insert_instruction(to_insert, index=i)
                inst.operands[j] = var
                i += 1

            i += 1

    def _process_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi"

        replacements: dict[IRVariable, IRVariable] = {}
        for label, var in inst.phi_operands:
            assert isinstance(var, IRVariable)
            bb = self.function.get_basic_block(label.name)
            term = bb.instructions[-1]
            assert term.is_bb_terminator
            new_var = self.updater.add_before(term, "assign", [var])
            assert new_var is not None
            replacements[var] = new_var

        inst.replace_operands(replacements)

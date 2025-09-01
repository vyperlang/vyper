from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable
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
        self.phis: list[IRInstruction] = []
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        for inst in self.phis:
            self._process_phi(inst)

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
                self.phis.append(inst)
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

                var = self.updater.add_before(inst, "assign", [op])
                assert var is not None
                ops = inst.operands.copy()
                ops[j] = var
                self.updater.update(inst, inst.opcode, ops)
                i += 1

            i += 1

    def _process_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi"

        replacements: dict[IROperand, IROperand] = {}
        for label, var in inst.phi_operands:
            assert isinstance(var, IRVariable)
            # you only care about the cases which would be not correct
            # as an output of this pass
            # example
            #
            #   bb1:
            #       ...
            #       ; it does not matter that the %origin is here for the phi instruction
            #       ; since if this is the only place where the origin is used
            #       ; other then the phi node then the phi node does not have to add
            #       ; additional store for it as and input to phi
            #       %var = %origin
            #       ...
            #       jmp @bb2
            #   bb2:
            #       ; the %origin does not have to be extracted to new varible
            #       ; since the only place where it is used is assign instruction
            #       %phi = phi @bb1, %origin, @someother, %somevar
            #       ...

            # if the only other use would be in assigns then the variable
            # does not have to be moved out to the new assign
            uses = [use for use in self.dfg.get_uses(var) if use.opcode != "assign"]

            # if the only other use would be in phi node in the some other block then
            # the same rule applies
            uses = [use for use in uses if use.opcode != "phi" or use.parent == inst.parent]
            if len(uses) <= 1:
                continue
            bb = self.function.get_basic_block(label.name)
            term = bb.instructions[-1]
            assert term.is_bb_terminator
            new_var = self.updater.add_before(term, "assign", [var])
            assert new_var is not None
            replacements[var] = new_var

        self.updater.update_operands(inst, replacements)

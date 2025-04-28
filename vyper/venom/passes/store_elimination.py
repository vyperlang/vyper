from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class StoreElimination(IRPass):
    """
    This pass forwards variables to their uses though `store` instructions,
    and removes the `store` instruction.
    """

    # TODO: consider renaming `store` instruction, since it is confusing
    # with LoadElimination

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for var, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "store":
                continue
            self._process_store(inst, var, inst.operands[0])

        for var, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_store(self, inst, var: IRVariable, new_var: IRVariable):
        """
        Process store instruction. If the variable is only used by a load instruction,
        forward the variable to the load instruction.
        """
        if False and any([inst.opcode == "phi" for inst in self.dfg.get_uses(new_var)]):
            return

        uses = self.dfg.get_uses(var)
        if False and any([inst.opcode == "phi" for inst in uses]):
            return
        for use_inst in uses.copy():
            self.updater.update_operands(use_inst, {var: new_var})

        self.updater.remove(inst)

    def _process_phi(self, inst: IRInstruction):
        inputs = set(var for _, var in inst.phi_operands)

        if len(inputs) == 1:
            self.updater.store(inst, inputs.pop())
            return

        translate_dict: dict = dict()

        for label, var in inst.phi_operands:
            src = self.dfg.get_producing_instruction(var)
            bb = self.function.get_basic_block(label.name)
            # assert src is not None
            # if src is not None and src.parent == bb:
            # continue

            new_var = self.updater.add_before(bb.instructions[-1], "store", [var])

            assert var not in translate_dict, (inst, var, translate_dict)
            translate_dict[var] = new_var

        self.updater.update_operands(inst, translate_dict)

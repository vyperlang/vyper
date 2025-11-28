from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class AssignElimination(IRPass):
    """
    This pass forwards variables to their uses though `store` instructions,
    and removes the `store` instruction. In the future we will probably rename
    the `store` instruction to `"assign"`.
    """

    # TODO: consider renaming `store` instruction, since it is confusing
    # with LoadElimination

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for var, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "assign":
                continue
            self._process_store(inst, var, inst.operands[0])

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_store(self, inst, var: IRVariable, new_var: IRVariable):
        """
        Process store instruction. If the variable is only used by a load instruction,
        forward the variable to the load instruction.
        """
        if any([inst.opcode == "phi" for inst in self.dfg.get_uses(new_var)]):
            return

        uses = self.dfg.get_uses(var)
        if any([inst.opcode == "phi" for inst in uses]):
            return
        for use_inst in uses.copy():
            self.updater.update_operands(use_inst, {var: new_var})

        self.updater.remove(inst)

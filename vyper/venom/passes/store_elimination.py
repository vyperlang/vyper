from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRVariable
from vyper.venom.passes.base_pass import IRPass


class StoreElimination(IRPass):
    """
    This pass forwards variables to their uses though `store` instructions,
    and removes the `store` instruction.
    """

    # TODO: consider renaming `store` instruction, since it is confusing
    # with LoadElimination

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for var, inst in self.dfg.outputs.items():
            if inst.opcode != "store":
                continue
            self._process_store(inst, var, inst.operands[0])

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

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
            for i, operand in enumerate(use_inst.operands):
                if operand == var:
                    use_inst.operands[i] = new_var

            self.dfg.add_use(new_var, use_inst)
            self.dfg.remove_use(var, use_inst)

        inst.parent.remove_instruction(inst)

from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRVariable
from vyper.venom.passes.base_pass import IRPass


class StoreElimination(IRPass):
    """
    This pass forwards variables to their uses though `store` instructions,
    and removes the `store` instruction.
    """

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for var, inst in dfg.outputs.items():
            if inst.opcode != "store":
                continue
            if not isinstance(inst.operands[0], IRVariable):
                continue
            if inst.operands[0].name in ["%ret_ofst", "%ret_size"]:
                continue
            if inst.output.name in ["%ret_ofst", "%ret_size"]:
                continue
            self._process_store(dfg, inst, var, inst.operands[0])

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_store(self, dfg, inst, var, new_var):
        """
        Process store instruction. If the variable is only used by a load instruction,
        forward the variable to the load instruction.
        """
        uses = dfg.get_uses(var)

        if any([inst.opcode == "phi" for inst in uses]):
            return

        for use_inst in uses:
            for i, operand in enumerate(use_inst.operands):
                if operand == var:
                    use_inst.operands[i] = new_var

        inst.parent.remove_instruction(inst)

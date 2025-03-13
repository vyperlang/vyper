from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, VarDefinition
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass


class SimplifyPhiPass(IRPass):
    """
    Eliminates phi nodes with identical operands.

    In SSA form, phi nodes at control flow joins select values based on
    which branch was taken. When all operands of a phi node are identical,
    the phi node is redundant and can be replaced with a simple assignment.
    """

    def run_pass(self):
        """
        Run the SimplifyPhi pass on the function.

        Returns:
            bool: True if any changes were made, False otherwise.
        """
        changed = False
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue

                if self._simplify_phi_if_identical_operands(inst):
                    changed = True

        if changed:
            # Invalidate dependent analyses
            cache = self.analyses_cache
            cache.invalidate_analysis(DFGAnalysis)
            cache.invalidate_analysis(LivenessAnalysis)
            cache.invalidate_analysis(VarDefinition)

        return changed

    def _simplify_phi_if_identical_operands(self, inst: IRInstruction) -> bool:
        """
        Check if a phi has identical operands and simplify it if so.

        A phi has operands in pairs: (label1, value1, label2, value2...)
        If all values match, replace with a simple store instruction.

        Args:
            inst: The phi instruction to check and potentially simplify

        Returns:
            bool: True if the phi was simplified, False otherwise
        """
        phi_operands = list(inst.phi_operands)

        assert len(phi_operands) > 0, "Phi instruction has no operands"

        _, first_value = phi_operands[0]

        if all(val == first_value for _, val in phi_operands):
            inst.opcode = "store"
            inst.operands = [first_value]
            return True

        return False

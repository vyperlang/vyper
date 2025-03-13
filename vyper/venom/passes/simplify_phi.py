from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, VarDefinition,DominatorTreeAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass, InstUpdater


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
        # Request the DFG analysis to determine variable equivalence
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.doms = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.updater = InstUpdater(self.dfg)

        changed = False
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue

                if self._handle_phi(inst):
                    changed = True

        if changed:
            # Invalidate dependent analyses
            cache = self.analyses_cache
            cache.invalidate_analysis(DFGAnalysis)
            cache.invalidate_analysis(LivenessAnalysis)
            cache.invalidate_analysis(VarDefinition)

        return changed

    def _handle_phi(self, inst: IRInstruction) -> bool:
        """
        Check if a phi has identical operands and simplify it if so.

        A phi has operands in pairs: (label1, value1, label2, value2...)
        If all values are semantically equivalent, replace with a simple store instruction.

        Args:
            inst: The phi instruction to check and potentially simplify
            dfg: The data flow graph analysis to use for equivalence checking

        Returns:
            bool: True if the phi was simplified, False otherwise
        """
        values = [val for _label, val in inst.phi_operands]

        assert len(values) > 0, "Phi instruction has no operands"

        value_sources = [self.dfg._traverse_store_chain(val) for val in values]

        if not all(val == value_sources[0] for val in value_sources):
            return False

        # the value to replace
        value = value_sources[0]
        source_inst = self.dfg.get_producing_instruction(value)
        assert source_inst is not None  # help mypy
        # it's not defined in all cfg_in blocks
        if inst.parent not in self.doms.dominated[source_inst.parent]:
            return False

        self.updater.store(inst, value)
        return True

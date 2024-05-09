
from vyper.utils import OrderedSet
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass

class VariableForwarding(IRPass):
    """
    This pass forwards variables to their uses though `store` instructions.
    """

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.var_name_count = 0
        for var, inst in dfg.outputs.items():
            if inst.opcode != "store":
                continue
            self._process_store(dfg, var, inst.operands[0])
            inst.parent.remove_instruction(inst)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_store(self, dfg, var, new_var):
        """
        Process store instruction. If the variable is only used by a load instruction,
        forward the variable to the load instruction.
        """
        uses = dfg.get_uses(var)
        for inst in uses:
            for i, operand in enumerate(inst.operands):
                if operand == var:
                    inst.operands[i] = new_var
            

from vyper.venom.passes.base_pass import IRPass
from vyper.venom.basicblock import IRVariable
from vyper.venom.analysis import DFGAnalysis

class RemoveNamesDBGPass(IRPass):
    dfg : DFGAnalysis

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis) #type: ignore
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                dbg_var = IRVariable(inst.opcode)
                
                for (i, op) in enumerate(inst.operands.copy()):
                    if not isinstance(op, IRVariable):
                        continue
                    src_inst = self.dfg.get_producing_instruction(op)
                    assert src_inst is not None
                    assert src_inst.output is not None

                    inst.operands[i] = src_inst.output
                
                inst.output = dbg_var


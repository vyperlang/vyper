from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRInstruction, IRVariable
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis

class RemoveInvalidPhiPass(IRPass):
    dfg : DFGAnalysis
    
    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions.copy():
                if inst.opcode == "phi":
                    self._handle_phi(inst)

    def _handle_phi(self, phi_inst : IRInstruction) -> bool:
        if len(phi_inst.parent.cfg_in) != 1:
            return False
        
        src_bb : IRBasicBlock = phi_inst.parent.cfg_in.first()
        assert isinstance(src_bb, IRBasicBlock)

        from_src_bb = filter(lambda x : x[0] == src_bb.label, phi_inst.phi_operands)
        operands = list(map(lambda x : x[1], from_src_bb))

        assert len(operands) == 1
        assert isinstance(operands[0], IRVariable)
        phi_inst.output.value = operands[0]
        phi_inst.parent.remove_instruction(phi_inst)

        return True




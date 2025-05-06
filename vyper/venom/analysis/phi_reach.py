from vyper.venom.analysis import DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable


class PhiReachingAnalysis(IRAnalysis):
    """
    Analyze the sources of possible inputs to phi instructions.
    Traverses the DFG through stores and phi (possibly including
    cycles) to find the original instructions which end up being
    inputs to phis.
    """

    dfg: DFGAnalysis
    phi_to_origins: dict[IRInstruction, set[IRInstruction]]

    def analyze(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.phi_to_origins = dict()

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    break
                self._handle_phi(inst)

        for src_insts in self.phi_to_origins.values():
            # sanity check (it could be triggered if we get invalid venom)
            assert all(src.opcode != "phi" for src in src_insts)

    def _handle_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi"
        self._handle_inst_r(inst)

    def _handle_inst_r(self, inst: IRInstruction) -> set[IRInstruction]:
        if inst.opcode == "phi":
            if inst in self.phi_to_origins:
                # phi is the only place where we can get dfg cycles.
                # break the recursion.
                return self.phi_to_origins[inst]

            self.phi_to_origins[inst] = set()

            for _, var in inst.phi_operands:
                next_inst = self.dfg.get_producing_instruction(var)
                assert next_inst is not None, (inst, var)
                self.phi_to_origins[inst] |= self._handle_inst_r(next_inst)
            return self.phi_to_origins[inst]

        if inst.opcode == "store" and isinstance(inst.operands[0], IRVariable):
            # traverse store chain
            var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(var)
            assert next_inst is not None
            return self._handle_inst_r(next_inst)

        return set([inst])

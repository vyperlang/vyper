from vyper.venom.analysis import DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable


class PhiReachingAnalysis(IRAnalysis):
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
        visited: set[IRInstruction] = set()
        self._handle_inst_r(inst, visited)

    def _handle_inst_r(
        self, inst: IRInstruction, visited: set[IRInstruction]
    ) -> set[IRInstruction]:
        if inst.opcode == "phi":
            if inst in visited:
                # phi is the only place where we can get dfg cycles.
                # break the recursion.
                return self.phi_to_origins[inst]
            visited.add(inst)

            for _, var in inst.phi_operands:
                next_inst = self.dfg.get_producing_instruction(var)
                assert next_inst is not None, (inst, var)
                self.phi_to_origins.setdefault(inst, set())
                self.phi_to_origins[inst] |= self._handle_inst_r(next_inst, visited)
            return self.phi_to_origins[inst]

        if inst.opcode == "store" and isinstance(inst.operands[0], IRVariable):
            # traverse store chain
            var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(var)
            assert next_inst is not None
            return self._handle_inst_r(next_inst, visited)

        return set([inst])

from vyper.venom.analysis import DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable


class PhiReachingAnalysis(IRAnalysis):
    dfg: DFGAnalysis
    phi_to_origins: dict[IRInstruction, set[IRInstruction]]

    def analyze(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.phi_to_origins = dict()
        self._compute_start()

        while True:
            change = False
            for inst in self.phi_to_origins.keys():
                change |= self._step(inst)
            if not change:
                break

    def _compute_start(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                self._starting_reach(inst)

    def _starting_reach(self, inst: IRInstruction):
        assert inst.opcode == "phi"
        inputs = set(var for _, var in inst.phi_operands)

        srcs: set[IRInstruction] = set()
        for op in inputs:
            src = self.dfg.get_producing_instruction(op)
            assert src is not None
            srcs.add(src)

        # pass through the assigns so we
        # have only canonical source for
        # operands (not done via store elimination
        # since that stops at phis
        for src in list(srcs):
            srcs.remove(src)
            while src.opcode == "store" and isinstance(src.operands[0], IRVariable):
                next_var = src.operands[0]
                next_src = self.dfg.get_producing_instruction(next_var)
                assert next_src is not None
                src = next_src
            srcs.add(src)

        self.phi_to_origins[inst] = srcs

    def _step(self, inst: IRInstruction) -> bool:
        srcs = self.phi_to_origins.get(inst, None)
        assert srcs is not None
        srcs = srcs.copy()

        for src in srcs:
            if src.opcode != "phi":
                continue
            next_srcs = self.phi_to_origins.get(src)
            assert next_srcs is not None
            self.phi_to_origins[inst].remove(src)
            self.phi_to_origins[inst] = self.phi_to_origins[inst].union(next_srcs)

        return srcs != self.phi_to_origins[inst]

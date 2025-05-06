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

    # TOOD: maybe we want to add this as a util method to DFGAnalysis
    def _get_store_root(self, inst: IRInstruction) -> IRInstruction:
        # pass through the assigns so we
        # have only canonical source for
        # operands (not done via store elimination
        # since that stops at phis
        while inst.opcode == "store" and isinstance(inst.operands[0], IRVariable):
            next_var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(next_var)
            assert next_inst is not None
            inst = next_inst
        return inst

    def _starting_reach(self, inst: IRInstruction):
        assert inst.opcode == "phi"
        inputs = set(var for _, var in inst.phi_operands)

        srcs: set[IRInstruction] = set()
        for op in inputs:
            src = self.dfg.get_producing_instruction(op)
            assert src is not None
            srcs.add(self._get_store_root(src))

        self.phi_to_origins[inst] = srcs

    def _step(self, inst: IRInstruction) -> bool:
        srcs = self.phi_to_origins[inst]
        srcs = srcs.copy()

        for src in srcs:
            if src.opcode != "phi":
                continue
            next_srcs = self.phi_to_origins[src]
            self.phi_to_origins[inst].remove(src)
            self.phi_to_origins[inst] |= next_srcs

        return srcs != self.phi_to_origins[inst]

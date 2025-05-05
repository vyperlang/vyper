from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.analysis import IRAnalysis
from vyper.venom.analysis import DFGAnalysis

class PhiReachingAnalysis(IRAnalysis):
    dfg: DFGAnalysis
    phi_to_origins: dict[IRInstruction, set[IRInstruction]]

    def analyze(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.phi_to_origins = dict()
        self._compute_start()

        while True:
            change = False
            for bb in self.function.get_basic_blocks():
                for inst in bb.instructions:
                    if inst.opcode != "phi":
                        continue

                    change |= self._step(inst)
            if not change:
                break 

    def _compute_start(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                self._basic_reach(inst)

    def _basic_reach(self, inst: IRInstruction):
        assert inst.opcode == "phi"
        inputs = set(var for _, var in inst.phi_operands)

        srcs: set[IRInstruction] = set()
        for op in inputs:
            src = self.dfg.get_producing_instruction(op)
            assert src is not None
            srcs.add(src)

        # this should not be necessary bu just for now
        while any(i.opcode == "store" and isinstance(i.operands[0], IRVariable) for i in srcs):
            for src in list(srcs):
                if src.opcode != "store":
                    continue
                if not isinstance(src.operands[0], IRVariable):
                    continue

                next_var = src.operands[0]
                srcs.remove(src)

                next_src = self.dfg.get_producing_instruction(next_var)
                assert next_src is not None

                srcs.add(next_src)

        self.phi_to_origins[inst] = srcs

    def _step(self, inst: IRInstruction) -> bool:
        srcs = self.phi_to_origins.get(inst, None)
        assert srcs is not None
        srcs = srcs.copy()

        for src in srcs:
            if src.opcode != "phi":
                continue
            src_srcs = self.phi_to_origins.get(src)
            assert src_srcs is not None
            self.phi_to_origins[inst].remove(src)
            self.phi_to_origins[inst] = self.phi_to_origins[inst].union(src_srcs)
        
        return srcs != self.phi_to_origins[inst]



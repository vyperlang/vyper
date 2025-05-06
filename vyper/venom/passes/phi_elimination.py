from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, PhiReachingAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class PhiEliminationPass(IRPass):
    phi_reach: PhiReachingAnalysis

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.phi_reach = self.analyses_cache.request_analysis(PhiReachingAnalysis)

        for _, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_phi(self, inst: IRInstruction):
        srcs = self.phi_reach.phi_to_origins.get(inst)
        assert srcs is not None

        if len(srcs) == 1:
            src = next(iter(srcs))
            assert src.output is not None
            self.updater.store(inst, src.output)

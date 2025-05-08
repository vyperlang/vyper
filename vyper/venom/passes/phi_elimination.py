from vyper.venom.analysis import DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class PhiEliminationPass(IRPass):
    phi_to_origins: dict[IRInstruction, set[IRInstruction]]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._calculate_phi_origin()

        for _, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_phi(self, inst: IRInstruction):
        srcs = self.phi_to_origins[inst]

        if len(srcs) == 1:
            src = srcs.pop()
            if src == inst:
                return
            assert src.output is not None
            self.updater.store(inst, src.output)

    def _calculate_phi_origin(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.phi_to_origins = dict()

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    break
                self._handle_phi(inst)

    def _handle_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi"
        self._handle_inst_r(inst, inst.parent)

    def _handle_inst_r(self, inst: IRInstruction, origin_bb: IRBasicBlock) -> set[IRInstruction]:
        if inst.opcode == "phi":
            if inst in self.phi_to_origins:
                # phi is the only place where we can get dfg cycles.
                # break the recursion.
                srcs = self.phi_to_origins[inst]
                if len(srcs) > 1:
                    return set([inst])
                return srcs

            self.phi_to_origins[inst] = set()

            for _, var in inst.phi_operands:
                next_inst = self.dfg.get_producing_instruction(var)
                assert next_inst is not None, (inst, var)
                self.phi_to_origins[inst] |= self._handle_inst_r(next_inst, origin_bb)

            if len(self.phi_to_origins[inst]) > 1:
                return set([inst])
            return self.phi_to_origins[inst]

        if inst.opcode == "store" and isinstance(inst.operands[0], IRVariable):
            # traverse store chain
            var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(var)
            assert next_inst is not None
            return self._handle_inst_r(next_inst, origin_bb)

        return set([inst])

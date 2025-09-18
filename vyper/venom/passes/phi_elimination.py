from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class PhiEliminationPass(IRPass):
    phi_to_origins: dict[IRInstruction, set[IRInstruction]]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._calculate_phi_origins()

        for _, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        # sort phis to top of basic block
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
            self.updater.mk_assign(inst, src.output)

    def _calculate_phi_origins(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.phi_to_origins = dict()

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    break
                self._get_phi_origins(inst)

    def _get_phi_origins(self, inst: IRInstruction):
        assert inst.opcode == "phi"  # sanity
        visited: set[IRInstruction] = set()
        self.phi_to_origins[inst] = self._get_phi_origins_r(inst, visited)

    # traverse chains of phis and stores to get the "root" instructions
    # for phis.
    def _get_phi_origins_r(
        self, inst: IRInstruction, visited: set[IRInstruction]
    ) -> set[IRInstruction]:
        if inst.opcode == "phi":
            if inst in self.phi_to_origins:
                return self.phi_to_origins[inst]

            if inst in visited:
                # we have hit a dfg cycle. break the recursion.
                # if it is only visited we have found a self
                # reference, and we won't find anything more by
                # continuing the recursion.
                return set()

            visited.add(inst)

            res: set[IRInstruction] = set()

            for _, var in inst.phi_operands:
                next_inst = self.dfg.get_producing_instruction(var)
                assert next_inst is not None, (inst, var)
                res |= self._get_phi_origins_r(next_inst, visited)

            if len(res) > 1:
                # if this phi has more than one origin, then for future
                # phis, it is better to treat this as a barrier in the
                # graph traversal. for example (without basic blocks)
                #   %a = 1
                #   %b = 2
                #   %c = phi %a, %b  ; has two origins
                #   %d = %c
                #   %e = %d
                #   %f = phi %d, %e
                # in this case, %f should reduce to %c.
                return set([inst])
            return res

        if inst.opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            # traverse assignment chain
            var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(var)
            assert next_inst is not None
            return self._get_phi_origins_r(next_inst, visited)

        # root of the phi/assignment chain
        return set([inst])

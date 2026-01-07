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

        # len > 1: multiple origins, phi is doing real work, keep it.
        if len(srcs) == 1:
            src = next(iter(srcs))
            if src == inst:
                return
            self.updater.mk_assign(inst, src.output)

    def _calculate_phi_origins(self):
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
                # multi-origin phi: treat the phi itself as a "barrier" origin.
                # this is correct because the phi is a single SSA definition,
                # even though its runtime value varies. any downstream phi that
                # only references this barrier (through copies) can be safely
                # eliminated to an assign from the barrier's output.
                # example:
                #   %c = phi %a, %b  ; barrier (two origins)
                #   %d = %c
                #   %f = phi %d, %c  ; both paths lead to %c, so %f = %c
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

from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IROperand, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class PhiEliminationPass(IRPass):
    # phi -> set of (root instruction, variable produced by it). origins
    # are keyed by the produced variable and not just the instruction,
    # since different outputs of one multi-output instruction (e.g.
    # invoke) are distinct origins.
    phi_to_origins: dict[IRInstruction, set[tuple[IRInstruction, IROperand]]]

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
            ((src, var),) = srcs
            if src == inst:
                return
            self.updater.mk_assign(inst, var)

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
        self.phi_to_origins[inst] = self._get_phi_origins_r(inst, inst.output, visited)

    # traverse chains of phis and stores to get the "root" definitions
    # for phis. `var` is the ssa variable through which `inst` was
    # reached; it identifies which output of `inst` is the origin.
    def _get_phi_origins_r(
        self, inst: IRInstruction, var: IROperand, visited: set[IRInstruction]
    ) -> set[tuple[IRInstruction, IROperand]]:
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

            res: set[tuple[IRInstruction, IROperand]] = set()

            for _, op_var in inst.phi_operands:
                next_inst = self.dfg.get_producing_instruction(op_var)
                assert next_inst is not None, (inst, op_var)
                res |= self._get_phi_origins_r(next_inst, op_var, visited)

            if len(res) > 1:
                # multi-origin phi: treat the phi itself as a "barrier" origin.
                # this is correct because the phi is a single SSA definition,
                # even though its runtime value varies. any downstream phi that
                # only references this barrier (through copies) can be safely
                # eliminated to an assign from the barrier's output; this
                # increases the number of phis which can be eliminated.
                # example:
                #   %a = ...
                #   %b = ...
                #   %c = phi %a, %b  ; barrier (two origins)
                #   %d = %c
                #   %f = phi %d, %c  ; both paths lead to %c, so %f = %c
                return set([(inst, inst.output)])
            return res

        if inst.opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            # traverse assignment chain
            src_var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(src_var)
            assert next_inst is not None
            return self._get_phi_origins_r(next_inst, src_var, visited)

        # root of the phi/assignment chain. note that for multi-output
        # instructions (e.g. invoke), different outputs are distinct
        # origins, so the origin is identified by (inst, var).
        return set([(inst, var)])

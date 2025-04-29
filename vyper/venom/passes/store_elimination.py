from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class StoreElimination(IRPass):
    """
    This pass forwards variables to their uses though `store` instructions,
    and removes the `store` instruction.
    """

    # TODO: consider renaming `store` instruction, since it is confusing
    # with LoadElimination

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)


        for var, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        for var, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "store":
                continue
            self._process_store(inst, var, inst.operands[0])

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_store(self, inst, var: IRVariable, new_var: IRVariable):
        """
        Process store instruction. If the variable is only used by a load instruction,
        forward the variable to the load instruction.
        """
        if any([inst.opcode == "phi" for inst in self.dfg.get_uses(new_var)]):
            return

        uses = self.dfg.get_uses(var)
        if any([inst.opcode == "phi" for inst in uses]):
            return
        for use_inst in uses.copy():
            self.updater.update_operands(use_inst, {var: new_var})

        self.updater.remove(inst)

    def _process_phi(self, inst: IRInstruction):
        inputs = set(var for _, var in inst.phi_operands)

        if len(inputs) == 1:
            self.updater.store(inst, inputs.pop())
            return

        srcs: set[IRInstruction] = set()
        for op in inputs:
            src = self.dfg.get_producing_instruction(op)
            assert src is not None
            srcs.add(src)

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

        if len(srcs) == 1:
            new_var = srcs.pop().output
            assert new_var is not None
            self.updater.store(inst, new_var)
            return

from vyper.venom.passes.base_pass import InstUpdater, IRPass
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis

class PhiEliminationPass(IRPass):
    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for _, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)


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

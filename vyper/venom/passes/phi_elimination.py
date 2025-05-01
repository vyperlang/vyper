from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class PhiEliminationPass(IRPass):
    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for _, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_phi(self, inst: IRInstruction):
        inputs = set(var for _, var in inst.phi_operands)

        if len(inputs) == 1:
            # print(inst)
            self.updater.store(inst, inputs.pop())
            return

        srcs: set[IRInstruction] = set()
        for op in inputs:
            src = self.dfg.get_producing_instruction(op)
            assert src is not None
            srcs.add(src)

        orig_srcs: set[IRInstruction] = srcs.copy()

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
            # print(inst)
            assert new_var is not None
            for s in orig_srcs:
                # print(bef)
                tmp = s
                while tmp.output != new_var:
                    self.updater.add_before(tmp, "volstore", [new_var])
                    assert tmp.opcode == "store"
                    assert isinstance(tmp.operands[0], IRVariable)
                    next_var = tmp.operands[0]
                    tmp = self.dfg.get_producing_instruction(next_var)
                    assert tmp is not None
                # print(bef)
            self.updater.update(inst, "poke", [new_var])
            # self.updater.store(inst, new_var)
            # print(inst)
            return

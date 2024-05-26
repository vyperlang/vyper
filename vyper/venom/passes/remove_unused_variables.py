from vyper.utils import OrderedSet
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass


class RemoveUnusedVariablesPass(IRPass):
    dfg: DFGAnalysis
    work_list: OrderedSet[IRInstruction]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        work_list = OrderedSet()
        self.work_list = work_list

        for _, inst in self.dfg.outputs.items():
            work_list.add(inst)

        while len(work_list) > 0:
            inst = work_list.pop()
            self._process_instruction(inst)

    def _process_instruction(self, inst):
        """
        Process an instruction.
        """
        if inst.output is None:
            return
        if inst.volatile:
            return
        uses = self.dfg.get_uses(inst.output)
        if len(uses) > 0:
            return

        for operand in inst.get_inputs():
            new_uses = self.dfg.remove_use(operand, inst)
            for use in new_uses:
                self.work_list.add(use)

        inst.parent.remove_instruction(inst)

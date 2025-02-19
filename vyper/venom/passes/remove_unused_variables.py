from vyper.utils import OrderedSet, uniq
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass


class RemoveUnusedVariablesPass(IRPass):
    """
    This pass removes instructions that produce output that is never used.
    """

    dfg: DFGAnalysis
    work_list: OrderedSet[IRInstruction]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        work_list = OrderedSet()
        self.work_list = work_list

        uses = self.dfg.outputs.values()
        work_list.addmany(uses)

        while len(work_list) > 0:
            inst = work_list.pop()
            self._process_instruction(inst)

        for bb in self.function.get_basic_blocks():
            bb.clear_nops()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_instruction(self, inst):
        if inst.output is None:
            return
        if inst.is_volatile or inst.is_bb_terminator:
            return
        uses = self.dfg.get_uses(inst.output)
        if len(uses) > 0:
            return

        for operand in uniq(inst.get_input_variables()):
            self.dfg.remove_use(operand, inst)
            new_uses = self.dfg.get_uses(operand)
            self.work_list.addmany(new_uses)

        inst.parent.remove_instruction(inst)

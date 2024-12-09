from vyper.utils import OrderedSet
from vyper.venom import effects
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, ReachableAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.passes.base_pass import IRPass


class RemoveUnusedVariablesPass(IRPass):
    """
    This pass removes instructions that produce output that is never used.
    """

    dfg: DFGAnalysis
    work_list: OrderedSet[IRInstruction]
    last_msize_position: dict[IRBasicBlock, int]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.reachable = self.analyses_cache.request_analysis(ReachableAnalysis).reachable

        self.last_msize_position = {}
        self.instruction_index = {}
        for bb in self.function.get_basic_blocks():
            for idx in range(len(bb.instructions) - 1, -1, -1):
                inst = bb.instructions[idx]
                self.instruction_index[inst] = idx
                if inst.opcode == "msize" and bb not in self.last_msize_position:
                    self.last_msize_position[bb] = idx

        work_list = OrderedSet()
        self.work_list = work_list

        uses = self.dfg.outputs.values()
        work_list.addmany(uses)

        while len(work_list) > 0:
            inst = work_list.pop()
            self._process_instruction(inst)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _process_instruction(self, inst):
        if inst.output is None:
            return
        if inst.is_volatile or inst.is_bb_terminator:
            return
        bb = inst.parent
        if effects.MSIZE in inst.get_write_effects():
            # msize after memory touch
            if (
                bb in self.last_msize_position
                and self.instruction_index[inst] < self.last_msize_position[bb]
            ):
                return
            if any(reachable_bb in self.reachable[bb] for reachable_bb in self.last_msize_position):
                return

        uses = self.dfg.get_uses(inst.output)
        if len(uses) > 0:
            return

        for operand in inst.get_input_variables():
            self.dfg.remove_use(operand, inst)
            new_uses = self.dfg.get_uses(operand)
            self.work_list.addmany(new_uses)

        inst.parent.remove_instruction(inst)

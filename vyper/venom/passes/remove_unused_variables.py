from collections import defaultdict

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
    _msizes: dict[IRBasicBlock, int]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.reachable = self.analyses_cache.request_analysis(ReachableAnalysis).reachable

        self._msizes = defaultdict(list)
        self.instruction_index = {}
        for bb in self.function.get_basic_blocks():
            for idx, inst in enumerate(bb.instructions):
                inst = bb.instructions[idx]
                self.instruction_index[inst] = idx
                if inst.opcode == "msize":
                    self._msizes[bb].append(idx)

        work_list = OrderedSet()
        self.work_list = work_list

        uses = self.dfg.outputs.values()
        work_list.addmany(uses)

        while len(work_list) > 0:
            inst = work_list.pop()
            self._process_instruction(inst)

        for bb in self.function.get_basic_blocks():
            bb.clear_dead_instructions()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def has_msize(self, bb):
        return len(self._msizes[bb]) > 0

    def get_last_msize(self, bb):
        msizes = self._msizes[bb]
        if len(msizes) == 0:
            return None
        return max(msizes)

    def msize_barrier(self, inst):
        bb = inst.parent
        if not self.has_msize(bb):
            return False
        return self.instruction_index[inst] < self.get_last_msize(bb)

    def _process_instruction(self, inst):
        if inst.output is None:
            return
        if inst.is_volatile or inst.is_bb_terminator:
            return
        bb = inst.parent
        if effects.MSIZE in inst.get_write_effects():
            # msize after memory touch
            if self.msize_barrier(inst):
                return
            for next_bb in self._msizes:
                if next_bb in self.reachable[bb] and self.has_msize(next_bb):
                    return

        uses = self.dfg.get_uses(inst.output)
        if len(uses) > 0:
            return

        for operand in inst.get_input_variables():
            self.dfg.remove_use(operand, inst)
            new_uses = self.dfg.get_uses(operand)
            self.work_list.addmany(new_uses)

        # if we remove an msize, update the index
        if inst.opcode == "msize":
            self._msizes[bb].remove(self.instruction_index[inst])

        bb.mark_for_removal(inst)

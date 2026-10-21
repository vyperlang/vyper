from vyper.utils import OrderedSet, uniq
from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.load_analysis import LoadAnalysis
from vyper.venom.analysis.mem_alias import (
    MemoryAliasAnalysis,
    StorageAliasAnalysis,
    TransientAliasAnalysis,
)
from vyper.venom.analysis.mem_ssa import MemSSA, StorageSSA, TransientSSA
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
        changed = False

        uses = self.dfg.outputs.values()
        work_list.addmany(uses)

        while len(work_list) > 0:
            inst = work_list.pop()
            changed |= self._process_instruction(inst)

        for bb in self.function.get_basic_blocks():
            bb.clear_nops()

        if not changed:
            return

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        # invalidate the alias analyses directly: the LoadAnalysis/*SSA
        # invalidations below only cascade to them when the parent is
        # actually cached, but the alias analyses can also be requested
        # (and cached) on their own
        self.analyses_cache.invalidate_analysis(MemoryAliasAnalysis)
        self.analyses_cache.invalidate_analysis(StorageAliasAnalysis)
        self.analyses_cache.invalidate_analysis(TransientAliasAnalysis)
        self.analyses_cache.invalidate_analysis(LoadAnalysis)
        self.analyses_cache.invalidate_analysis(MemSSA)
        self.analyses_cache.invalidate_analysis(StorageSSA)
        self.analyses_cache.invalidate_analysis(TransientSSA)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_instruction(self, inst) -> bool:
        outputs = inst.get_outputs()
        if len(outputs) == 0:
            return False
        if inst.is_volatile or inst.is_bb_terminator:
            return False

        # Check if ANY output has uses
        for output in outputs:
            uses = self.dfg.get_uses(output)
            if len(uses) > 0:
                return False

        for operand in uniq(inst.get_input_variables()):
            self.dfg.remove_use(operand, inst)
            new_uses = self.dfg.get_uses(operand)
            self.work_list.addmany(new_uses)

        inst.make_nop()
        return True

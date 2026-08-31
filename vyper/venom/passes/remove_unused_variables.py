from vyper.evm import address_space
from vyper.utils import OrderedSet, uniq
from vyper.venom import effects
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.mem_alias import can_create_mem_alias, mem_alias_type_factory
from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.load_analysis import LoadAnalysis
from vyper.venom.analysis.mem_alias import (
    MemoryAliasAnalysis,
    StorageAliasAnalysis,
    TransientAliasAnalysis,
)
from vyper.venom.analysis.mem_ssa import MemSSA, StorageSSA, TransientSSA
from vyper.venom.basicblock import IRInstruction
from vyper.venom.effects import EMPTY, FMP
from vyper.venom.passes.base_pass import IRPass


class RemoveUnusedVariablesPass(IRPass):
    """
    This pass removes instructions that produce output that is never used.
    """

    dfg: DFGAnalysis
    work_list: OrderedSet[IRInstruction]

    invalidate_alias: set[address_space.AddrSpace]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.invalidate_alias = set()

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
        self.analyses_cache.invalidate_analysis(StorageAliasAnalysis)
        self.analyses_cache.invalidate_analysis(TransientAliasAnalysis)
        self.analyses_cache.invalidate_analysis(LoadAnalysis)
        self.analyses_cache.invalidate_analysis(MemSSA)
        self.analyses_cache.invalidate_analysis(StorageSSA)
        self.analyses_cache.invalidate_analysis(TransientSSA)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        for space in self.invalidate_alias:
            alias_analysis = mem_alias_type_factory(space)
            self.analyses_cache.invalidate_analysis(alias_analysis)

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

        # instructions that handle FMP can be removed if there is no use for the
        # since they either bump or set only at the end of the function so the
        # removal of the instruction will not effect other instructions.
        # Other write effect should not be removed by this analysis
        assert inst.get_write_effects() == EMPTY or inst.get_write_effects() == FMP
        effs = inst.get_read_effects()
        if effs != EMPTY:
            for eff in effs:
                space = effects.to_addr_space(eff)
                if space is None:
                    # sanity check
                    assert eff == FMP, eff
                # Mem alias does not use all address spaces
                elif can_create_mem_alias(space):
                    self.invalidate_alias.add(space)

        inst.make_nop()
        return True

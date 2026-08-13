from vyper.evm import address_space
from vyper.utils import OrderedSet, uniq
from vyper.venom import effects
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.mem_alias import mem_alias_type_factory
from vyper.venom.basicblock import IRInstruction
from vyper.venom.effects import EMPTY
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

        uses = self.dfg.outputs.values()
        work_list.addmany(uses)

        while len(work_list) > 0:
            inst = work_list.pop()
            self._process_instruction(inst)

        for bb in self.function.get_basic_blocks():
            bb.clear_nops()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        for space in self.invalidate_alias:
            alias_analysis = mem_alias_type_factory(space)
            self.analyses_cache.invalidate_analysis(alias_analysis)


    def _process_instruction(self, inst: IRInstruction):
        outputs = inst.get_outputs()
        if len(outputs) == 0:
            return
        if inst.is_volatile or inst.is_bb_terminator:
            return

        # Check if ANY output has uses
        for output in outputs:
            uses = self.dfg.get_uses(output)
            if len(uses) > 0:
                return

        for operand in uniq(inst.get_input_variables()):
            self.dfg.remove_use(operand, inst)
            new_uses = self.dfg.get_uses(operand)
            self.work_list.addmany(new_uses)

        assert inst.get_write_effects() == EMPTY
        eff = inst.get_read_effects()
        if eff != EMPTY:
            space = effects.to_addr_space(eff)
            assert space is not None
            self.invalidate_alias.add(space)            

        inst.make_nop()

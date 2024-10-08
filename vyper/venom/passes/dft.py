from collections import defaultdict

import vyper.venom.effects as effects
from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    function: IRFunction
    visited_instructions: OrderedSet[IRInstruction]
    ida: dict[IRInstruction, OrderedSet[IRInstruction]]
    barriers: dict[IRInstruction, OrderedSet[IRInstruction]]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)

    def run_pass(self) -> None:
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._calculate_dependency_graphs(bb)
        self.instructions = list(bb.pseudo_instructions)
        non_phi_instructions = list(bb.non_phi_instructions)

        # Compute entry points in the graph of instruction dependencies
        entry_instructions: OrderedSet[IRInstruction] = OrderedSet(non_phi_instructions)
        for inst in non_phi_instructions:
            to_remove = self.ida.get(inst, OrderedSet())
            if len(to_remove) > 0:
                entry_instructions.dropmany(to_remove)

        # Move the terminator instruction to the end of the list
        terminator = next(inst for inst in entry_instructions if inst.is_bb_terminator)
        assert terminator is not None, f"Basic block should have a terminator instruction {bb}"
        entry_instructions.remove(terminator)
        entry_instructions.add(terminator)

        self.visited_instructions = OrderedSet()
        for inst in entry_instructions:
            self._process_instruction_r(self.instructions, inst)

        bb.instructions = self.instructions
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.is_pseudo:
            return

        for barrier_inst in self.barriers[inst]:
            self._process_instruction_r(instructions, barrier_inst)

        for dep_inst in self.ida[inst]:
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)

    def _calculate_dependency_graphs(self, bb: IRBasicBlock) -> None:
        # ida: instruction dependency analysis
        self.ida = defaultdict(OrderedSet)
        self.barriers = defaultdict(OrderedSet)

        non_phis = list(bb.non_phi_instructions)

        #
        # Compute dependency graph
        #
        last_write_effects: dict[effects.Effects, IRInstruction] = {}
        last_read_effects: dict[effects.Effects, IRInstruction] = {}
        for inst in non_phis:
            for op in inst.operands:
                dep = self.dfg.get_producing_instruction(op)
                if dep is not None and dep.parent == bb:
                    self.ida[inst].add(dep)

            write_effects = inst.get_write_effects()
            read_effects = inst.get_read_effects()

            for write_effect in write_effects:
                if write_effect in last_write_effects and last_write_effects[write_effect] != inst:
                    self.barriers[inst].add(last_write_effects[write_effect])
                if write_effect in last_read_effects:
                    self.barriers[inst].add(last_read_effects[write_effect])
                last_write_effects[write_effect] = inst

            for read_effect in read_effects:
                if read_effect in last_write_effects and last_write_effects[read_effect] != inst:
                    self.barriers[inst].add(last_write_effects[read_effect])
                last_read_effects[read_effect] = inst

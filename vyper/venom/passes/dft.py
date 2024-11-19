from collections import defaultdict

import vyper.venom.effects as effects
from vyper.utils import OrderedSet
from vyper.venom.analysis import DFGAnalysis, IRAnalysesCache, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    function: IRFunction
    data_offspring: dict[IRInstruction, OrderedSet[IRInstruction]]
    effects_offspring: dict[IRInstruction, OrderedSet[IRInstruction]]
    visited_instructions: OrderedSet[IRInstruction]
    # data dependencies
    dda: dict[IRInstruction, OrderedSet[IRInstruction]]
    # effect dependencies
    eda: dict[IRInstruction, OrderedSet[IRInstruction]]

    def run_pass(self) -> None:
        self.data_offspring = {}
        self.effects_offspring = {}
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self._calculate_dependency_graphs(bb)
        self.instructions = list(bb.pseudo_instructions)
        non_phi_instructions = list(bb.non_phi_instructions)

        self.visited_instructions = OrderedSet()
        for inst in bb.instructions:
            self._calculate_effects_offspring(inst)
            self._calculate_data_offspring(inst)

        # Compute entry points in the graph of instruction dependencies
        entry_instructions: OrderedSet[IRInstruction] = OrderedSet(non_phi_instructions)
        for inst in non_phi_instructions:
            to_remove = self.dda.get(inst, OrderedSet()) | self.eda.get(inst, OrderedSet())
            entry_instructions.dropmany(to_remove)

        entry_instructions_list = list(entry_instructions)

        self.visited_instructions = OrderedSet()
        for inst in entry_instructions_list:
            self._process_instruction_r(self.instructions, inst)

        bb.instructions = self.instructions
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.is_pseudo:
            return

        children = list(self.dda[inst] | self.eda[inst])

        shared = OrderedSet()
        if len(self.eda[inst]) > 0:
            shared = OrderedSet.intersection(*[self.data_offspring[x] for x in self.eda[inst]])

        def cost(x: IRInstruction) -> int|float:
            ret = 0
            #if x.output in inst.operands and not inst.is_commutative and not inst.is_comparator:
            if x in self.eda[inst] or inst.is_commutative or inst.is_comparator:
                #ret = -len(self.data_offspring[x] - shared) * 0.5
                #ret = -len(self.data_offspring[x]) / len(inst.operands) # max(1, len(self.data_offspring[inst]))
                ret = -(len(self.data_offspring[x]) > 0)
            elif x in self.dda[inst]:
                ret = inst.operands.index(x.output) == len(inst.operands) - 1
            else: # pragma: nocover
                raise CompilerPanic("unreachable")
            return ret

        # heuristic: sort by size of child dependency graph
        orig_children = children.copy()
        children.sort(key=cost)

        if inst.is_commutative or inst.is_comparator and (orig_children != children):
            if inst.is_commutative:
                inst.operands.reverse()
            else:
                inst.flip_comparison()

        for dep_inst in children:
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)

    def _calculate_dependency_graphs(self, bb: IRBasicBlock) -> None:
        # ida: instruction dependency analysis
        self.dda = defaultdict(OrderedSet)
        self.eda = defaultdict(OrderedSet)

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
                    self.dda[inst].add(dep)

            write_effects = inst.get_write_effects()
            read_effects = inst.get_read_effects()

            for write_effect in write_effects:
                if write_effect in last_read_effects:
                    self.eda[inst].add(last_read_effects[write_effect])
                last_write_effects[write_effect] = inst

            for read_effect in read_effects:
                if read_effect in last_write_effects and last_write_effects[read_effect] != inst:
                    self.eda[inst].add(last_write_effects[read_effect])
                last_read_effects[read_effect] = inst

    def _calculate_effects_offspring(self, inst: IRInstruction):
        if inst in self.effects_offspring:
            return self.effects_offspring[inst]

        self.effects_offspring[inst] = self.eda[inst].copy()

        deps = self.eda[inst]
        for dep_inst in deps:
            assert inst.parent == dep_inst.parent
            res = self._calculate_effects_offspring(dep_inst)
            self.effects_offspring[inst] |= res

        return self.effects_offspring[inst]

    def _calculate_data_offspring(self, inst: IRInstruction):
        if inst in self.data_offspring:
            return self.data_offspring[inst]

        self.data_offspring[inst] = self.dda[inst].copy()

        deps = self.dda[inst]
        for dep_inst in deps:
            assert inst.parent == dep_inst.parent
            res = self._calculate_data_offspring(dep_inst)
            self.data_offspring[inst] |= res

        return self.data_offspring[inst]

from collections import defaultdict, deque

import vyper.venom.effects as effects
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.stack_order import StackOrderAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    function: IRFunction
    data_offspring: dict[IRInstruction, OrderedSet[IRInstruction]]
    visited_instructions: OrderedSet[IRInstruction]
    # "data dependency analysis"
    dda: dict[IRInstruction, OrderedSet[IRInstruction]]
    # "effect dependency analysis"
    eda: dict[IRInstruction, OrderedSet[IRInstruction]]

    stack_order: StackOrderAnalysis
    cfg: CFGAnalysis
    # DFT expects single-use-expanded operands and should run just before CFG normalization.
    required_predecessors = ("SingleUseExpansion",)
    required_immediate_successors = ("CFGNormalization",)

    def run_pass(self) -> None:
        self.data_offspring = {}
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.stack_order = StackOrderAnalysis(self.analyses_cache)

        worklist = deque(self.cfg.dfs_post_walk)

        last_order: dict[IRBasicBlock, list[IRVariable]] = dict()

        while len(worklist) > 0:
            bb = worklist.popleft()
            self.stack_order.analyze_bb(bb)
            order = self.stack_order.get_stack(bb)
            if bb in last_order and last_order[bb] == order:
                break
            last_order[bb] = order
            self.order = list(reversed(order))
            self._process_basic_block(bb)

            for pred in self.cfg.cfg_in(bb):
                worklist.append(pred)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self._calculate_dependency_graphs(bb)
        self.instructions = list(bb.pseudo_instructions)
        non_phi_instructions = list(bb.non_phi_instructions)

        self.visited_instructions = OrderedSet()
        for inst in bb.instructions:
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

        def cost(x: IRInstruction) -> int | float:
            # intuition:
            #   effect-only dependencies which have data dependencies
            #   effect-only dependencies which have no data dependencies
            #   indirect data dependencies (offspring of operands)
            #   direct data dependencies (order of operands)

            is_effect_only = x not in self.dda[inst] and x in self.eda[inst]
            if is_effect_only or inst.flippable:
                has_data_offspring = len(self.data_offspring[x]) > 0
                return -1 if has_data_offspring else 0

            assert x in self.dda[inst]  # sanity check

            # locate operands that are produced by x and prefer earliest match
            operand_idxs = [
                i
                for i, op in enumerate(inst.operands)
                if self.dfg.get_producing_instruction(op) is x
            ]
            if len(operand_idxs) > 0:
                return min(operand_idxs) + len(self.order)

            outputs = x.get_outputs()
            operand_positions = [
                inst.operands.index(out_var) for out_var in outputs if out_var in inst.operands
            ]
            if len(operand_positions) > 0:
                return min(operand_positions) + len(self.order)

            order_positions = [
                self.order.index(out_var) for out_var in outputs if out_var in self.order
            ]
            if len(order_positions) > 0:
                return min(order_positions)

            # fall back to a stable default when no operand is associated
            return len(self.order)

        # heuristic: sort by size of child dependency graph
        orig_children = children.copy()
        children.sort(key=cost)

        if inst.flippable and (orig_children != children):
            inst.flip()

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
        all_read_effects: dict[effects.Effects, list[IRInstruction]] = defaultdict(list)

        for inst in non_phis:
            if inst.is_bb_terminator:
                for var in self.order:
                    dep = self.dfg.get_producing_instruction(var)
                    if dep is not None and dep.parent == bb:
                        self.dda[inst].add(dep)
            for op in inst.operands:
                dep = self.dfg.get_producing_instruction(op)
                if dep is not None and dep.parent == bb:
                    self.dda[inst].add(dep)

            write_effects = inst.get_write_effects()
            read_effects = inst.get_read_effects()

            for write_effect in write_effects:
                # ALL reads must happen before this write
                if write_effect in all_read_effects:
                    for read_inst in all_read_effects[write_effect]:
                        self.eda[inst].add(read_inst)
                # prevent reordering write-after-write for the same effect
                if (write_effect & ~effects.Effects.MSIZE) in last_write_effects:
                    self.eda[inst].add(last_write_effects[write_effect])
                last_write_effects[write_effect] = inst
                # clear previous read effects after a write
                if write_effect in all_read_effects:
                    all_read_effects[write_effect] = []

            for read_effect in read_effects:
                if read_effect in last_write_effects and last_write_effects[read_effect] != inst:
                    self.eda[inst].add(last_write_effects[read_effect])
                all_read_effects[read_effect].append(inst)

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

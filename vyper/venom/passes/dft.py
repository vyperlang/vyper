from collections import defaultdict, deque

import vyper.venom.effects as effects
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis, StackOrder
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand
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

    stack_order: StackOrder
    cfg: CFGAnalysis

    def run_pass(self) -> None:
        self.data_offspring = {}
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()
        self.stack_order = StackOrder(self.analyses_cache, self.function)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)

        self.stack_order.calculates_store_types()

        worklist = deque(self.cfg.dfs_post_walk)
        last_stack_orders: dict[IRBasicBlock, list] = dict()

        while len(worklist) > 0:
            bb = worklist.popleft()
            stack_order = self.stack_order.get_prefered_stack(bb, list(self.cfg.cfg_out(bb)))
            if bb in last_stack_orders and stack_order == last_stack_orders[bb]:
                continue
            last_stack_orders[bb] = stack_order
            self._process_basic_block(bb, stack_order)
            for inbb in self.cfg.cfg_in(bb):
                worklist.append(inbb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_basic_block(self, bb: IRBasicBlock, stack_order: list[IROperand]) -> None:
        self._calculate_dependency_graphs(bb, stack_order)
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
            self._process_instruction_r(self.instructions, inst, stack_order)
        bb.instructions = self.instructions
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _process_instruction_r(
        self, instructions: list[IRInstruction], inst: IRInstruction, stack_order: list[IROperand]
    ):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.is_pseudo:
            return

        children = list(self.dda[inst] | self.eda[inst])

        def cost(x: IRInstruction) -> int | float:
            if (x not in self.dda[inst] and x in self.eda[inst]) or inst.flippable:
                ret = -1 * int(len(self.data_offspring[x]) > 0)
            else:
                assert x in self.dda[inst]  # sanity check
                assert x.output is not None  # help mypy
                if x.output in inst.operands:
                    ret = inst.operands.index(x.output) + len(stack_order)
                else:
                    assert inst.is_bb_terminator
                    ret = stack_order.index(x.output)
            return ret

        # heuristic: sort by size of child dependency graph
        orig_children = children.copy()
        children.sort(key=cost)

        if inst.flippable and (orig_children != children):
            inst.flip()

        for dep_inst in children:
            self._process_instruction_r(instructions, dep_inst, stack_order)

        instructions.append(inst)

    def _calculate_dependency_graphs(self, bb: IRBasicBlock, out_stack: list[IROperand]) -> None:
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
                for op in out_stack:
                    dep = self.dfg.get_producing_instruction(op)
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
                if write_effect in last_write_effects:
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

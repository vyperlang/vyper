from collections import defaultdict, deque
from typing import Optional

import vyper.venom.effects as effects
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis, StackOrderAnalysis
from vyper.venom.analysis.mem_ssa import MemSSAAbstract, mem_ssa_type_factory
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.passes.base_pass import IRPass

# effects whose dependency edges are filtered with memory SSA alias info
_FILTERED_EFFECTS = (effects.MEMORY, effects.STORAGE, effects.TRANSIENT)

# an access of a filtered effect: the instruction and the location memory
# SSA resolved for it. None means the instruction is not tracked by memory
# SSA (e.g. `invoke`) and may touch anything.
_Access = tuple[IRInstruction, Optional[MemoryLocation]]


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
    mem_ssa: dict[effects.Effects, MemSSAAbstract]
    # DFT expects single-use-expanded operands and should run just before CFG normalization.
    required_predecessors = ("SingleUseExpansion",)
    required_immediate_successors = ("CFGNormalization",)

    def run_pass(self) -> None:
        self.data_offspring = {}
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.stack_order = self.analyses_cache.force_analysis(StackOrderAnalysis)
        self.mem_ssa = {}
        for eff in _FILTERED_EFFECTS:
            addr_space = effects.to_addr_space(eff)
            assert addr_space is not None, eff
            mem_ssa_type = mem_ssa_type_factory(addr_space)
            self.mem_ssa[eff] = self.analyses_cache.request_analysis(mem_ssa_type)

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
        # memory SSA reaching-def chains follow instruction order
        for mem_ssa in self.mem_ssa.values():
            self.analyses_cache.invalidate_analysis(type(mem_ssa))

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
        # for the filtered effects: the prior writes and reads a later access
        # may still need an edge to (see _add_write_deps)
        prior_writes: dict[effects.Effects, list[_Access]] = defaultdict(list)
        prior_reads: dict[effects.Effects, list[_Access]] = defaultdict(list)

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
                if write_effect in self.mem_ssa:
                    writes = prior_writes[write_effect]
                    reads = prior_reads[write_effect]
                    self._add_write_deps(write_effect, inst, writes, reads)
                    continue
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
                if read_effect in self.mem_ssa:
                    writes = prior_writes[read_effect]
                    reads = prior_reads[read_effect]
                    self._add_read_deps(read_effect, inst, writes, reads)
                    continue
                if read_effect in last_write_effects and last_write_effects[read_effect] != inst:
                    self.eda[inst].add(last_write_effects[read_effect])
                all_read_effects[read_effect].append(inst)

    def _add_write_deps(
        self, eff: effects.Effects, inst: IRInstruction, writes: list[_Access], reads: list[_Access]
    ) -> None:
        mem_def = self.mem_ssa[eff].get_memory_def(inst)
        loc = mem_def.loc if mem_def is not None else None

        for read_inst, read_loc in reads:
            if self._may_alias(eff, loc, read_loc):
                self.eda[inst].add(read_inst)
        for write_inst, write_loc in writes:
            if self._may_alias(eff, loc, write_loc):
                self.eda[inst].add(write_inst)

        # a later access which aliases an access this write covers also
        # aliases this write, so its edge to this write already orders it
        # after the covered access. drop the covered accesses; this keeps
        # the graph a chain (and the scan linear) when nothing is resolved.
        reads[:] = [a for a in reads if not self._covers(loc, a[1])]
        writes[:] = [a for a in writes if not self._covers(loc, a[1])]
        writes.append((inst, loc))

    def _add_read_deps(
        self, eff: effects.Effects, inst: IRInstruction, writes: list[_Access], reads: list[_Access]
    ) -> None:
        mem_use = self.mem_ssa[eff].get_memory_use(inst)
        loc = mem_use.loc if mem_use is not None else None

        for write_inst, write_loc in writes:
            # an instruction which both reads and writes does not depend on itself
            if write_inst is not inst and self._may_alias(eff, loc, write_loc):
                self.eda[inst].add(write_inst)
        reads.append((inst, loc))

    def _may_alias(
        self, eff: effects.Effects, loc_a: Optional[MemoryLocation], loc_b: Optional[MemoryLocation]
    ) -> bool:
        if loc_a is None or loc_b is None:
            return True
        # the alias analysis treats distinct allocations as disjoint. that
        # holds in program order, but FmpLoweringPass reclaims a dead dynamic
        # allocation by restoring the FMP to its mark, so a later `bump` can
        # hand out the same memory. reordering across such a reuse is exactly
        # what this pass does, so keep the fence between different allocations.
        if loc_a.alloca is not None and loc_b.alloca is not None and loc_a.alloca != loc_b.alloca:
            return True
        return self.mem_ssa[eff].memalias.may_alias(loc_a, loc_b)

    @staticmethod
    def _covers(loc: Optional[MemoryLocation], other: Optional[MemoryLocation]) -> bool:
        # every access aliasing `other` also aliases `loc` (under _may_alias)
        if loc is None:
            return True
        if loc.offset is None and not loc.is_empty():
            # an unknown offset may alias anything
            return True
        if other is None:
            return False
        return loc.completely_contains(other)

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

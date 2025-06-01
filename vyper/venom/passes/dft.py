from collections import defaultdict
from typing import Dict, List, Optional

import vyper.venom.effects as effects
from vyper.utils import OrderedSet
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.mem_ssa import (
    LiveOnEntry,
    MemoryAccess,
    MemoryDef,
    MemoryPhi,
    MemoryUse,
    MemSSA,
    MemSSAAbstract,
)
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    function: IRFunction
    data_offspring: dict[IRInstruction, OrderedSet[IRInstruction]]
    visited_instructions: OrderedSet[IRInstruction]
    # "data dependency analysis"
    dda: dict[IRInstruction, OrderedSet[IRInstruction]]
    # "effect dependency analysis"
    eda: dict[IRInstruction, OrderedSet[IRInstruction]]

    effective_reaching_defs: dict[MemoryUse, MemoryDef]
    defs_to_uses: Dict[MemoryDef, List[MemoryUse]]

    def run_pass(self) -> None:
        self.data_offspring = {}
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)
        self.mem_ssa = self.analyses_cache.force_analysis(MemSSA)
        self._calculate_effective_reaching_defs()

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

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
            if x in self.eda[inst] or inst.flippable:
                ret = -1 * int(len(self.data_offspring[x]) > 0)
            else:
                assert x in self.dda[inst]  # sanity check
                assert x.output is not None  # help mypy
                ret = inst.operands.index(x.output)
            return ret

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
                if read_effect == effects.MEMORY:
                    self._handle_memory_effect(inst, last_write_effects, last_read_effects)
                    continue
                if read_effect in last_write_effects and last_write_effects[read_effect] != inst:
                    self.eda[inst].add(last_write_effects[read_effect])
                last_read_effects[read_effect] = inst

    def _handle_memory_effect(
        self,
        inst: IRInstruction,
        last_write_effects: dict[effects.Effects, IRInstruction],
        last_read_effects: dict[effects.Effects, IRInstruction],
    ) -> None:
        mem_use = self.mem_ssa.get_memory_use(inst)
        mem_def = self.effective_reaching_defs.get(mem_use, None)

        if mem_def is not None and isinstance(mem_def, MemoryDef):
            if mem_def.inst.parent == inst.parent:
                self.eda[inst].add(mem_def.inst)                 
        elif (
            effects.MEMORY in last_write_effects
            and last_write_effects[effects.MEMORY] != inst
        ):
            self.eda[inst].add(last_write_effects[effects.MEMORY])

        last_read_effects[effects.MEMORY] = inst

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

    def _calculate_effective_reaching_defs(self):
        self.effective_reaching_defs = {}
        self.defs_to_uses: Dict[MemoryDef, List[MemoryUse]] = {}
        for mem_use in self.mem_ssa.get_memory_uses():
            if mem_use.inst.opcode != "mload":
                continue
            #if isinstance(mem_use.inst.operands[0], IRVariable):
            #    continue
            mem_def = self._walk_for_effective_reaching_def(
                mem_use.reaching_def, mem_use.loc, OrderedSet()
            )
            self.effective_reaching_defs[mem_use] = mem_def
            if mem_def not in self.defs_to_uses:
                self.defs_to_uses[mem_def] = []
            self.defs_to_uses[mem_def].append(mem_use)

    def _walk_for_effective_reaching_def(
        self, mem_access: MemoryAccess, query_loc: MemoryLocation, visited: OrderedSet[MemoryAccess]
    ) -> Optional[MemoryDef | MemoryPhi | LiveOnEntry]:
        current: Optional[MemoryAccess] = mem_access
        while current is not None:
            if current in visited:
                break
            visited.add(current)

            if isinstance(current, MemoryDef):
                if self.mem_ssa.memalias.may_alias(query_loc, current.loc):
                    return current

            if isinstance(current, MemoryPhi):
                reaching_defs = []
                for access, _ in current.operands:
                    reaching_def = self._walk_for_effective_reaching_def(access, query_loc, visited)
                    if reaching_def:
                        reaching_defs.append(reaching_def)
                if len(reaching_defs) == 1:
                    return reaching_defs[0]

                return current

            current = current.reaching_def

        return MemSSAAbstract.live_on_entry

from dataclasses import dataclass
import time
from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass
import itertools
import random

@dataclass
class Group:
    group_id: int
    root: IRInstruction
    volatile: bool

    def __hash__(self) -> int:
        return self.group_id

class DFTPass(IRPass):
    function: IRFunction
    inst_order: dict[IRInstruction, int]
    inst_order_num: int
    inst_groups: dict[IRInstruction, Group]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.inst_groups = {}
        random.seed(10)

    def _permutate(self, instructions: list[IRInstruction]):
        return random.shuffle(instructions)

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.is_phi:
            return

        children = [self.dfg.get_producing_instruction(op) for op in inst.get_input_variables()]
        
        for dep_inst in self.ida[inst]:
            if dep_inst in self.visited_instructions:
                continue
            if dep_inst in children:
                continue
            self._process_instruction_r(instructions, dep_inst)

        for dep_inst in children:
            if dep_inst in self.visited_instructions:
                continue
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._calculate_ida(bb)
        self.instructions = list(bb.phi_instructions)

        for g in self.groups:
            self._process_instruction_r(self.instructions, g.root)

        bb.instructions = self.instructions #[:-1]
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _calculate_ida(self, bb: IRBasicBlock) -> None:
        self.ida = dict[IRInstruction, list[IRInstruction]]()
        self.gda = dict[Group, OrderedSet[Group]]()

        non_phis = list(bb.non_phi_instructions)

        for inst in non_phis:
            self.ida[inst] = list()

        self.inst_groups = {}
        self.groups = []

        for inst in non_phis:
            outputs = inst.get_outputs()

            if len(outputs) == 0:
                self.groups.append(Group(len(self.groups), inst, False))
                self.inst_groups[inst] = self.groups[-1]
                continue
            for op in outputs:
                uses = self.dfg.get_uses(op)
                uses_count = 0
                for uses_this in uses:
                    if uses_this.parent != inst.parent:
                        continue
                    self.ida[uses_this].append(inst)
                    uses_count += 1
                if uses_count == 0:
                    self.groups.append(Group(len(self.groups), inst, False))
                    self.inst_groups[inst] = self.groups[-1]

        def mark_group_r(g: Group, inst: IRInstruction):
            for inst in self.ida[inst]:
                if self.inst_groups.get(inst) is not None:
                    continue
                self.inst_groups[inst] = g
                mark_group_r(g, inst)

        for g in self.groups:
            mark_group_r(g, g.root)

        for g in self.groups:
            self.gda[g] = OrderedSet()

        for inst, next_inst in zip(non_phis, non_phis[1:]):
            if not inst.is_volatile:
                continue
            self.gda[self.inst_groups[inst]].add(self.inst_groups[next_inst]) 

        for inst in reversed(non_phis):
            if not inst.is_volatile:
                continue
            g = self.inst_groups[inst]
            assert g is not None, f"Group not found for {inst}"
            for op in inst.get_input_variables():
                uses = self.dfg.get_uses(op)
                for uses_this in uses:
                    uses_group = self.inst_groups[uses_this]
                    if uses_group == g:
                        continue
                    self.gda[g].add(uses_group)

        

        if bb.label.value == "1_then":
            print(self.gda_as_graph())
            import sys
            sys.exit(1)

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def ida_as_graph(self) -> str:
        lines = ["digraph ida_graph {"]
        for inst, deps in self.ida.items():
            for dep in deps:
                a = inst.str_short()
                b = dep.str_short()
                a = a.replace("%", "\\%")
                b = b.replace("%", "\\%")
                lines.append(f'"{a}" -> "{b}"')
        lines.append("}")
        return "\n".join(lines)
    
    def gda_as_graph(self) -> str:
        lines = ["digraph gda_graph {"]
        for g, deps in self.gda.items():
            for dep in deps:
                a = g.root.str_short()
                b = dep.root.str_short()
                a = a.replace("%", "\\%")
                b = b.replace("%", "\\%")
                lines.append(f'"{a}" -> "{b}"')
        lines.append("}")
        return "\n".join(lines)

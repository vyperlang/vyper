import random
from dataclasses import dataclass

from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass

count = 0


@dataclass
class Group:
    group_id: int
    dependants: list["Group"]
    root: IRInstruction
    volatile: bool

    def __init__(self, group_id: int, root: IRInstruction, volatile: bool):
        self.group_id = group_id
        self.dependants = []
        self.root = root
        self.volatile = volatile

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
            if inst.parent != dep_inst.parent:
                continue
            if dep_inst in self.visited_instructions:
                continue
            if self.inst_groups.get(dep_inst) != self.inst_groups.get(inst):
                continue
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._calculate_ida(bb)
        self.instructions = list(bb.phi_instructions)

        for g in self._get_group_order(bb):
            self._process_instruction_r(self.instructions, g.root)

        bb.instructions = self.instructions
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _get_group_order(self, bb: IRBasicBlock) -> list[Group]:
        exit_group = self.inst_groups[bb.instructions[-1]]
        groups = []
        groups_visited = set()

        def _walk_group_r(group: Group):
            if group in groups_visited:
                return
            groups_visited.add(group)

            neighbors = list(self.gda[group])
            for g in neighbors:
                if g in groups_visited:
                    continue
                _walk_group_r(g)

            groups.append(group)

        for g in self.groups:
            g.dependants = []

        for g in self.groups:
            for dep in self.gda.get(g, []):
                dep.dependants.append(g)

        groups_visited.add(exit_group)
        for g in self.groups:
            if len(g.dependants) == 0:
                _walk_group_r(g)
        for g in self.groups:
            _walk_group_r(g)
        groups_visited.remove(exit_group)

        _walk_group_r(exit_group)

        return groups

    def _calculate_ida(self, bb: IRBasicBlock) -> None:
        self.ida = dict[IRInstruction, list[IRInstruction]]()
        self.gda = dict[Group, OrderedSet[Group]]()

        non_phis = list(bb.non_phi_instructions)

        for inst in non_phis:
            self.ida[inst] = list()

        self.inst_groups = {}
        self.groups = list[Group]()
        # self.inst_groups[non_phis[0]] = self.groups[-1]

        for inst in non_phis:
            outputs = inst.get_outputs()

            if len(outputs) == 0:
                self.groups.append(Group(len(self.groups), inst, False))
                self.inst_groups[inst] = self.groups[-1]
                continue
            if inst.is_volatile:
                self.groups.append(Group(len(self.groups), inst, False))
                self.inst_groups[inst] = self.groups[-1]
            for op in outputs:
                uses = self.dfg.get_uses(op)
                uses_count = 0
                for uses_this in uses:
                    if uses_this.parent != inst.parent:
                        continue
                    self.ida[uses_this].append(inst)
                    uses_count += 1
                if uses_count == 0 and not inst.is_volatile:
                    self.groups.append(Group(len(self.groups), inst, False))
                    self.inst_groups[inst] = self.groups[-1]

        def mark_group_r(g: Group, instruction: IRInstruction):
            for inst in self.ida[instruction]:
                if self.inst_groups.get(inst) is not None:
                    continue
                self.inst_groups[inst] = g
                mark_group_r(g, inst)

        for g in self.groups:
            mark_group_r(g, g.root)

        for g in self.groups:
            self.gda[g] = OrderedSet()

        last_volatile = None
        for inst, next_inst in reversed(list(zip(non_phis, non_phis[1:]))):
            if not inst.is_volatile:
                continue
            if self.inst_groups[inst] == self.inst_groups[next_inst]:
                continue
            if self.inst_groups[next_inst] in self.gda.get(self.inst_groups[inst], OrderedSet()):
                continue
            if last_volatile:
                self.gda[self.inst_groups[last_volatile]].add(self.inst_groups[inst])
            ga = self.inst_groups[next_inst]
            gb = self.inst_groups[inst]
            self.gda[ga].add(gb)
            if inst.is_volatile:
                last_volatile = inst

        for inst in reversed(non_phis):
            # if not inst.is_volatile:
            #     continue
            g = self.inst_groups[inst]
            assert g is not None, f"Group not found for {inst}"
            for op in inst.get_input_variables():
                prod = self.dfg.get_producing_instruction(op)
                if prod.is_phi:
                    continue
                if prod.parent != inst.parent:
                    continue
                prod_group = self.inst_groups.get(prod)
                assert prod_group is not None, f"Group not found for {prod}"
                if prod_group == g:
                    continue
                if g in self.gda.get(prod_group, OrderedSet()):
                    continue
                self.gda[g].add(prod_group)

        # cycles = find_cycles_in_directed_graph(self.gda)

        # global count
        # if bb.label.value == "__main_entry" and count == 1:
        #     print(self.gda_as_graph())
        #     import sys
        #     sys.exit(1)
        # count += 1

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
                if s := self.inst_groups.get(inst):
                    a += f" {s.group_id}"
                if s := self.inst_groups.get(dep):
                    b += f" {s.group_id}"
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
                a += f" {g.group_id}"
                b += f" {dep.group_id}"
                a = a.replace("%", "\\%")
                b = b.replace("%", "\\%")
                lines.append(f'"{a}" -> "{b}"')
        lines.append("}")
        return "\n".join(lines)

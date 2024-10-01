import random
import sys

from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    function: IRFunction
    inst_offspring_count: dict[IRInstruction, int]
    visited_instructions: OrderedSet[IRInstruction]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.inst_offspring_count = {}

    def _permutate(self, instructions: list[IRInstruction]):
        return random.shuffle(instructions)

    def _calculate_instruction_offspring_count_r(self, inst: IRInstruction):
        if inst in self.visited_instructions:
            return

        self.visited_instructions.add(inst)
        self.inst_offspring_count[inst] = 1

        for dep_inst in self.ida[inst]:
            if inst.parent != dep_inst.parent:
                continue
            self._calculate_instruction_offspring_count_r(dep_inst)
            self.inst_offspring_count[inst] += self.inst_offspring_count[dep_inst]

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.is_pseudo:
            return

        children = sorted(
            self.ida[inst],
            key=lambda x: (
                -self.inst_offspring_count[x] + (x.opcode == "iszero") * 10,
                inst.operands.index(x.output) if x.output in inst.operands else 0,
            ),
        )

        for dep_inst in children:
            if inst.parent != dep_inst.parent:
                continue
            if dep_inst in self.visited_instructions:
                continue
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._calculate_dependency_graphs(bb)
        self.instructions = list(bb.pseudo_instructions)

        self.visited_instructions = OrderedSet()
        for inst in reversed(list(bb.non_phi_instructions)):
            self._calculate_instruction_offspring_count_r(inst)

        self.visited_instructions = OrderedSet()
        non_phi_instructions = list(bb.non_phi_instructions)
        for inst in reversed(non_phi_instructions):
            self._process_instruction_r(self.instructions, inst)

        bb.instructions = self.instructions
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _calculate_dependency_graphs(self, bb: IRBasicBlock) -> None:
        # ida: instruction dependency analysis
        self.ida = dict[IRInstruction, list[IRInstruction]]()
        # gda: group dependency analysis

        non_phis = list(bb.non_phi_instructions)

        for inst in non_phis:
            self.ida[inst] = list()

        #
        # Apply effects to dependency graph
        #
        last_effects = {}
        last_volatile = None
        terminator_inst = non_phis[-1]
        for inst in non_phis:
            uses = self.dfg.get_uses_in_bb(inst.output, inst.parent)

            for use in uses:
                self.ida[use].append(inst)
                
            if inst.is_volatile:
                if terminator_inst.opcode in ["exit", "ret", "stop", "return", "jmp"]:
                    self.ida[terminator_inst].append(inst)

            if inst.is_volatile:
                last_volatile = inst

            read_effects = inst.get_read_effects()
            write_effects = inst.get_write_effects()

            for write_effect in write_effects:
                if write_effect in last_effects:
                    self.ida[inst].append(last_effects[write_effect])
                last_effects[write_effect] = inst

            for read_effect in read_effects:
                if read_effect in last_effects:
                    self.ida[inst].append(last_effects[read_effect])

            

            

    def run_pass(self) -> None:
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

        self.analyses_cache.request_analysis(LivenessAnalysis)

    #
    # Graphviz output for debugging
    #
    def ida_as_graph(self) -> str:
        lines = ["digraph ida_graph {"]
        for inst, deps in self.ida.items():
            for dep in deps:
                a = inst.str_short()
                b = dep.str_short()
                a += f" {self.inst_count.get(inst, " - ")}"
                b += f" {self.inst_count.get(dep, " - ")}"
                a = a.replace("%", "\\%")
                b = b.replace("%", "\\%")
                lines.append(f'"{a}" -> "{b}"')
        lines.append("}")
        return "\n".join(lines)

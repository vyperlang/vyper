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

class DFTPass(IRPass):
    function: IRFunction
    inst_order: dict[IRInstruction, int]
    inst_order_num: int
    inst_groups: dict[IRInstruction, int]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.inst_groups = {}
        self.start = IRInstruction("start", [])
        random.seed(10)

    def _permutate(self, instructions: list[IRInstruction]):
        return random.shuffle(instructions)

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        children = self.ida[inst]
        if inst.opcode == "start":
            if len(children) > 0 and children[-1].is_bb_terminator:
                leading = children[:-1]
                random.shuffle(leading)
                children[:-1] = leading
                #children[:-1] = reversed(children[:-1])
            else:
                random.shuffle(children)
        else:
            children = list((children))
            #random.shuffle(children)

        for dep_inst in children:
            if dep_inst in self.visited_instructions:
                continue
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._calculate_ida(bb)
        self.instructions = list(bb.phi_instructions)

        self._process_instruction_r(self.instructions, self.start)

        bb.instructions = self.instructions[:-1]
        assert bb.is_terminated, f"Basic block should be terminated {bb}"

    def _calculate_ida(self, bb: IRBasicBlock) -> None:
        self.ida = dict[IRInstruction, list[IRInstruction]]()

        for inst in bb.non_phi_instructions:
            self.ida[inst] = list()

        self.start = IRInstruction("start", [])
        self.ida[self.start] = list()
        self.inst_groups = {}

        for inst in bb.non_phi_instructions:
            if inst.is_volatile:
                idx = bb.instructions.index(inst)
                for inst2 in bb.instructions[idx + 1 :]:
                    self.ida[inst2].append(inst)

            outputs = inst.get_outputs()

            if len(outputs) == 0:
                self.ida[self.start].append(inst)
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
                    self.ida[self.start].append(inst)

        # if bb.label.value == "1_then":
        #     print(self.ida_as_graph())
        #     import sys
        #     sys.exit(1)

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

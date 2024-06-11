from collections import deque
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.utils import OrderedSet
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    function: IRFunction
    inst_order: dict[IRInstruction, int]
    inst_order_num: int
    inst_groups: dict[int, list[IRInstruction]]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.inst_groups = {}
        self.start = IRInstruction("start", [])

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)
            
        for dep_inst in self.ida[inst]:
            if dep_inst in self.visited_instructions:
                continue
            self._process_instruction_r(instructions, dep_inst)

        instructions.append(inst)     

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._calcualte_ida(bb)
        self.instructions = deque()

        self._process_instruction_r(self.instructions, self.start)
        self.instructions.pop()  # remove the start instruction

        bb.instructions = list(self.instructions)

    def _calcualte_ida(self, bb: IRBasicBlock) -> None:
        self.ida = dict[IRInstruction, list[IRInstruction]]()

        for inst in bb.instructions:
            self.ida[inst] = list()

        self.start = IRInstruction("start", [])
        self.ida[self.start] = list()
        
        for inst in bb.instructions:
            outputs = inst.get_outputs()
            if len(outputs) == 0:
                self.ida[self.start].append(inst)
                continue
            for op in outputs:
                uses = self.dfg.get_uses(op)
                for uses_this in uses:
                    if uses_this.parent != inst.parent:
                        continue
                    self.ida[uses_this].append(inst)

            if inst.is_volatile:
                idx = bb.instructions.index(inst)
                for inst2 in bb.instructions[idx + 1:]:
                    self.ida[inst2].append(inst)

        self.ida[self.start].sort(key=lambda x: 1 if x.is_bb_terminator else 0)

    def ida_as_graph(self) -> str:
        lines = ["digraph ida_graph {"]
        for inst, deps in self.ida.items():
            for dep in deps:
                a = inst.str_short()
                b = dep.str_short()
                a=a.replace('%', '\\%')
                b=b.replace('%', '\\%')
                lines.append(f'"{a}" -> "{b}"')
        lines.append("}")
        return "\n".join(lines)

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        #if self.function._basic_block_dict.get("5_if_exit") is not None:
        #    self._calcualte_ida(self.function.get_basic_block("5_if_exit"))

        self.fence_id = 1
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

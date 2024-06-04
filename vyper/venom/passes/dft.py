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

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        for op in inst.get_outputs():
            uses = self.dfg.get_uses(op)

            for uses_this in uses:
                if uses_this.parent != inst.parent:
                    # don't reorder across basic block boundaries
                    continue

                if uses_this.fence_id != inst.fence_id:
                    # don't reorder across fence boundaries
                    continue
                
                self._process_instruction_r(instructions, uses_this)

            #instructions.extend(forward_instructions)            
        
        # if inst.opcode == "phi":
        #     # phi instructions stay at the beginning of the basic block
        #     # and no input processing is needed
        #     # bb.instructions.append(inst)
        #     self.instructions.appendleft(inst)
        #     return

        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)
        
        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            assert target is not None, f"no producing instruction for {op}"
            if target.parent != inst.parent:
                # don't reorder across basic block boundaries
                continue
            if target.fence_id != inst.fence_id:
                # don't reorder across fence boundaries
                continue
            self._process_instruction_r(instructions, target)

        instructions.append(inst)        

    def _add_to_group(self, inst: IRInstruction) -> None:
        group = self.inst_groups.get(inst.fence_id)
        if group is None:
            self.inst_groups[inst.fence_id] = [inst]
        else:
            group.append(inst)

    def _assign_fences(self, bb: IRBasicBlock) -> None:
        self.inst_groups = {}
        self.visited = OrderedSet()
        bb.instructions[-1].fence_id = 0
        self._add_to_group(bb.instructions[-1])

        for inst in reversed(bb.instructions[:-1]):
            self._assign_fences_r(inst, 1)

    def _assign_fences_r(self, inst: IRInstruction, fence_id: int) -> None:
        if inst in self.visited:
            return
        self.visited.add(inst)

        inst.fence_id = fence_id
        self._add_to_group(inst)

        for op in inst.get_outputs():
            uses = self.dfg.get_uses(op)
            for uses_this in uses:
                if uses_this.parent != inst.parent:
                    continue
                self._assign_fences_r(uses_this, fence_id)
        
        

        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            if target.parent != inst.parent:
                continue

            self._assign_fences_r(target, fence_id)

        if inst.is_volatile:
            fence_id += 1
        

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._assign_fences(bb)

        self.inst_order = {}
        self.inst_order_num = len(bb.instructions)

        self.instructions = deque()

        instructions_per_group = {}
        for i, group in self.inst_groups.items():
            instructions_per_group[i] = deque()
            for inst in group:
                instructions = []
                self._process_instruction_r(instructions, inst)    
                instructions_per_group[i].extendleft(reversed(instructions))

        for i, group in reversed(instructions_per_group.items()):
            self.instructions.extend(group)

        # for inst in reversed(bb.instructions):
        #     instructions = []
        #     self._process_instruction_r(instructions, inst)
        #     self.instructions.extendleft(reversed(instructions))

        bb.instructions = list(self.instructions)

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.analyses_cache.force_analysis(LivenessAnalysis)

        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

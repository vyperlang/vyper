from collections import deque
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

    def _process_instruction_r(self, instructions: list[IRInstruction], inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        for op in inst.get_outputs():
            uses = self.dfg.get_uses(op)

            forward_instructions = []
            for uses_this in uses:
                if uses_this.parent != inst.parent:
                    # don't reorder across basic block boundaries
                    continue

                if uses_this.fence_id != inst.fence_id:
                    # don't reorder across fence boundaries
                    continue
                
                self._process_instruction_r(forward_instructions, uses_this)

            instructions.extend(forward_instructions)            
        
        # if inst.opcode == "phi":
        #     # phi instructions stay at the beginning of the basic block
        #     # and no input processing is needed
        #     # bb.instructions.append(inst)
        #     self.instructions.appendleft(inst)
        #     return
        
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
# SPLIT THE IN SEPARATE LISTS PER FENCE
        instructions.append(inst)        

    def _assign_fences(self, bb: IRBasicBlock) -> None:
        self.visited = OrderedSet()
        bb.instructions[-1].fence_id = 0
        self.fence_id = 1
        for inst in reversed(bb.instructions[:-1]):
            self._assign_fences_r(inst)

    def _assign_fences_r(self, inst: IRInstruction) -> None:
        if inst in self.visited:
            return
        self.visited.add(inst)

        inst.fence_id = self.fence_id

        for op in inst.get_outputs():
            uses = self.dfg.get_uses(op)
            for uses_this in uses:
                if uses_this.parent != inst.parent:
                    continue
                self._assign_fences_r(uses_this)
        
        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            if target.parent != inst.parent:
                continue

            self._assign_fences_r(target)

        if inst.is_volatile:
            self.fence_id += 1

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._assign_fences(bb)

        self.inst_order = {}
        self.inst_order_num = len(bb.instructions)

        self.instructions = deque()

        for inst in reversed(bb.instructions):
            instructions = []
            self._process_instruction_r(instructions, inst)
            self.instructions.extendleft(reversed(instructions))

        bb.instructions = list(self.instructions)

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.analyses_cache.force_analysis(LivenessAnalysis)

        self.fence_id = 1
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

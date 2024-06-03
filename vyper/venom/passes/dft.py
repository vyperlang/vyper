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

    def _process_instruction_r(self, bb: IRBasicBlock, inst: IRInstruction, offset: int = 0):
        for op in inst.get_outputs():
            assert isinstance(op, IRVariable), f"expected variable, got {op}"
            uses = self.dfg.get_uses(op)

            for uses_this in uses:
                if uses_this.parent != inst.parent:
                    # don't reorder across basic block boundaries
                    continue

                if inst.fence_id != 0 and uses_this.fence_id != inst.fence_id:
                    # don't reorder across fence boundaries
                    continue

                # if the instruction is a terminator, we need to place
                # it at the end of the basic block
                # along with all the instructions that "lead" to it
                self._process_instruction_r(bb, uses_this, offset)

        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)
        self.inst_order_num += 1

        if inst.is_bb_terminator:
            offset = len(bb.instructions)

        if inst.opcode == "phi":
            # phi instructions stay at the beginning of the basic block
            # and no input processing is needed
            # bb.instructions.append(inst)
            self.inst_order[inst] = 0
            return

        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            assert target is not None, f"no producing instruction for {op}"
            if target.parent != inst.parent:
                # don't reorder across basic block boundaries
                continue
            if target.fence_id != inst.fence_id:
                # don't reorder across fence boundaries
                continue
            self._process_instruction_r(bb, target, offset)

        self.inst_order[inst] = self.inst_order_num + offset

    def _assign_fences_dummy(self, bb: IRBasicBlock) -> None:
        for inst in bb.instructions:
            inst.fence_id = self.fence_id
            if inst.is_volatile:
                self.fence_id += 1

    def _assign_fences(self, bb: IRBasicBlock) -> None:
        self.visited = OrderedSet()
        self.fence_id = 1
        for inst in reversed(bb.instructions[:-1]):
            self._assign_fences_r(inst)

    def _assign_fences_r(self, inst: IRInstruction) -> None:
        if inst in self.visited:
            return
        self.visited.add(inst)

        inst.fence_id = self.fence_id
        if inst.is_volatile:
            self.fence_id += 1
        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            self._assign_fences_r(target)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.function.append_basic_block(bb)

        self._assign_fences(bb)

        # We go throught the instructions and calculate the order in which they should be executed
        # based on the data flow graph. This order is stored in the inst_order dictionary.
        # We then sort the instructions based on this order.
        self.inst_order = {}
        self.inst_order_num = 0
        for inst in bb.instructions:
            self._process_instruction_r(bb, inst)

        bb.instructions.sort(key=lambda x: self.inst_order[x])

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.analyses_cache.force_analysis(LivenessAnalysis)

        self.fence_id = 1
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = list(self.function.get_basic_blocks())

        self.function.clear_basic_blocks()
        for bb in basic_blocks:
            self._process_basic_block(bb)

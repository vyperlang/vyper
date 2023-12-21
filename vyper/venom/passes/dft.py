from vyper.utils import OrderedSet
from vyper.venom.analysis import DFG
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


# DataFlow Transformation
class DFTPass(IRPass):
    def _process_instruction_r(self, bb: IRBasicBlock, inst: IRInstruction):
        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.opcode == "phi":
            # phi instructions stay at the beginning of the basic block
            # and no input processing is needed
            bb.instructions.append(inst)
            return

        for op in inst.get_inputs():
            target = self.dfg.get_producing_instruction(op)
            if target.parent != inst.parent or target.fence_id != inst.fence_id:
                # don't reorder across basic block or fence boundaries
                continue
            self._process_instruction_r(bb, target)

        bb.instructions.append(inst)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.ctx.append_basic_block(bb)

        instructions = bb.instructions
        bb.instructions = []

        for inst in instructions:
            inst.fence_id = self.fence_id
            if inst.volatile:
                self.fence_id += 1

        for inst in instructions:
            self._process_instruction_r(bb, inst)

    def _run_pass(self, ctx: IRFunction) -> None:
        self.ctx = ctx
        self.dfg = DFG.build_dfg(ctx)
        self.fence_id = 0
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = ctx.basic_blocks
        ctx.basic_blocks = []

        for bb in basic_blocks:
            self._process_basic_block(bb)

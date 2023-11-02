from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.ir_pass import IRPass

# DataFlow Transformation
class DFTPass(IRPass):
    # recurse "down" into all the uses of `inst`, and then recurse "up" through
    # all of its dependencies, to try to product an ordering of instructions
    # which tries to optimize production of stack items to be as close as
    # possible to uses of stack items.
    def _process_instruction_r(self, bb: IRBasicBlock, inst: IRInstruction):
        # print("(inst)", inst)
        for op in inst.get_outputs():
            for target in self.ctx.dfg.get_uses(op):
                # print("(target)", target)
                if target.parent != inst.parent:
                    # don't reorder across basic block boundaries
                    continue
                if target.fence_id != inst.fence_id:
                    # don't reorder across fence groups
                    continue

                # try to find the last use
                self._process_instruction_r(bb, target)

        if inst in self.visited_instructions:
            return
        # print("VISITING", inst)
        self.visited_instructions.add(inst)

        if inst.opcode == "phi":
            # don't try to reorder inputs of phi
            bb.instructions.append(inst)
            return

        # print(inst.get_inputs(), inst)
        for op in inst.get_inputs():
            target = self.ctx.dfg.get_producing_instruction(op)
            if target.parent != inst.parent:
                continue
            # REVIEW: should there be a check for fence here? i.e.,
            # ```
            # if target.fence_id != inst.fence_id:
            #     continue
            # ```
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
        # print(ctx)
        self.ctx = ctx
        self.fence_id = 0
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = ctx.basic_blocks
        ctx.basic_blocks = []

        for bb in basic_blocks:
            self._process_basic_block(bb)

        # print(ctx)

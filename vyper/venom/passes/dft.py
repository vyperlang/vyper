from vyper.utils import OrderedSet
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRVariable,
    MemType,
)
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


# DataFlow Graph
class DFG:
    _dfg_inputs: dict[IRVariable, list[IRInstruction]]
    _dfg_outputs: dict[IRVariable, IRInstruction]

    def __init__(self):
        self._dfg_inputs = dict()
        self._dfg_outputs = dict()

    # return uses of a given variable
    def get_uses(self, op: IRVariable) -> list[IRInstruction]:
        return self._dfg_inputs.get(op, [])

    # the instruction which produces this variable.
    def get_producing_instruction(self, op: IRVariable) -> IRInstruction:
        return self._dfg_outputs[op]

    @classmethod
    def calculate_dfg(cls, ctx: IRFunction) -> None:
        dfg = DFG.from_ir_function(ctx)
        ctx.dfg = dfg

        dfg._compute_dup_requirements(ctx)

    def _compute_dup_requirements(self, ctx: IRFunction) -> None:
        for bb in ctx.basic_blocks:
            last_seen = dict()

            for inst in bb.instructions:
                # reset dup_requirements
                inst.dup_requirements = OrderedSet()

                for op in inst.get_inputs():
                    if op in last_seen:
                        target = last_seen[op]
                        target.dup_requirements.add(op)

                    last_seen[op] = inst

                    if op in bb.out_vars:
                        inst.dup_requirements.add(op)

    @classmethod
    def from_ir_function(cls, ctx: IRFunction):
        dfg = cls()

        # Build DFG

        # %15 = add %13 %14
        # %16 = iszero %15
        # dfg_outputs of %15 is (%15 = add %13 %14)
        # dfg_inputs of %15 is all the instructions which *use* %15, ex. [(%16 = iszero %15), ...]
        for bb in ctx.basic_blocks:
            for inst in bb.instructions:
                operands = inst.get_inputs()
                res = inst.get_outputs()

                for op in operands:
                    inputs = dfg._dfg_inputs.setdefault(op, [])
                    inputs.append(inst)

                for op in res:
                    dfg._dfg_outputs[op] = inst

        return dfg


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
        self.ctx = ctx
        self.fence_id = 0
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = ctx.basic_blocks
        ctx.basic_blocks = []

        for bb in basic_blocks:
            self._process_basic_block(bb)

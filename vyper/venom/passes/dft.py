from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


# DataFlow Graph
# this could be refactored into its own file, but it's only used here
# for now
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
    def build_dfg(cls, ctx: IRFunction):
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

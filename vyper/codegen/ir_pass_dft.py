from vyper.codegen.ir_basicblock import IRBasicBlock, IRInstruction
from vyper.codegen.ir_function import IRFunction
from vyper.utils import OrderedSet

visited_instructions = OrderedSet()


def _emit_operands_instruction(ctx: IRFunction, bb: IRBasicBlock, inst: IRInstruction):
    for op in inst.get_input_operands():
        target = ctx.dfg_outputs.get(op.value, None)
        if target is None:
            continue
        _process_instruction(ctx, bb, target)


def _process_instruction(ctx: IRFunction, bb: IRBasicBlock, inst: IRInstruction):
    global visited_instructions
    if inst in visited_instructions:
        return
    visited_instructions.add(inst)
    _emit_operands_instruction(ctx, bb, inst)
    bb.append_instruction(inst)


def _process_basic_block(ctx: IRFunction, bb: IRBasicBlock):
    ctx.append_basic_block(bb)
    instructions = bb.instructions
    bb.instructions = []
    for inst in instructions:
        _process_instruction(ctx, bb, inst)


def ir_pass_dft(ctx: IRFunction):
    global visited_instructions
    visited_instructions = OrderedSet()

    basic_blocks = ctx.basic_blocks
    ctx.basic_blocks = []

    for bb in basic_blocks:
        _process_basic_block(ctx, bb)

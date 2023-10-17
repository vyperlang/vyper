from vyper.codegen.ir_basicblock import IRBasicBlock, IRInstruction
from vyper.codegen.ir_function import IRFunction
from vyper.utils import OrderedSet

visited_instructions = OrderedSet()


def __process_instruction(ctx: IRFunction, bb: IRBasicBlock, inst: IRInstruction):
    for op in inst.get_output_operands():
        for target in ctx.dfg_inputs.get(op.value, []):
            if target.parent.label != bb.label:
                continue
            if target.volatile:
                continue
            _process_instruction(ctx, bb, target)

    if inst in visited_instructions:
        return
    visited_instructions.add(inst)

    bb.append_instruction(inst)


def _process_instruction(ctx: IRFunction, bb: IRBasicBlock, inst: IRInstruction):
    for op in inst.get_input_operands():
        target = ctx.dfg_outputs.get(op.value, None)
        if target.parent.label != bb.label:
            continue
        if target.volatile:
            continue
        _process_instruction(ctx, bb, target)

    if inst in visited_instructions:
        return
    visited_instructions.add(inst)

    bb.append_instruction(inst)


def _process_basic_block(ctx: IRFunction, _bb: IRBasicBlock):
    bb = _bb.copy()
    bb.parent = ctx
    ctx.append_basic_block(bb)
    bb.instructions = []
    for inst in _bb.instructions:
        _process_instruction(ctx, bb, inst)


def ir_pass_dft(_ctx: IRFunction):
    global visited_instructions

    visited_instructions = OrderedSet()

    ctx = _ctx.copy()
    ctx.basic_blocks = []

    for i in range(len(_ctx.basic_blocks)):
        _process_basic_block(ctx, _ctx.basic_blocks[i])

    return ctx

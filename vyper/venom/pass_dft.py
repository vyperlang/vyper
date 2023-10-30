from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.utils import OrderedSet, ir_pass

visited_instructions = OrderedSet()


def _emit_operands_instruction(ctx: IRFunction, bb: IRBasicBlock, inst: IRInstruction) -> None:
    for op in inst.get_inputs():
        target = ctx.dfg_outputs.get(op.value)
        if target is None:
            continue
        _process_instruction(ctx, bb, target)


def _process_instruction(ctx: IRFunction, bb: IRBasicBlock, inst: IRInstruction) -> None:
    global visited_instructions
    if inst in visited_instructions:
        return
    visited_instructions.add(inst)
    _emit_operands_instruction(ctx, bb, inst)
    bb.append_instruction(inst)


def _process_basic_block(ctx: IRFunction, bb: IRBasicBlock) -> None:
    ctx.append_basic_block(bb)
    instructions = bb.instructions
    bb.instructions = []
    for inst in instructions:
        _process_instruction(ctx, bb, inst)


@ir_pass
def ir_pass_dft(ctx: IRFunction) -> None:
    global visited_instructions
    visited_instructions = OrderedSet()

    basic_blocks = ctx.basic_blocks
    ctx.basic_blocks = []

    for bb in basic_blocks:
        _process_basic_block(ctx, bb)

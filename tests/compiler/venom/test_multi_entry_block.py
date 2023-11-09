from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental
from vyper.venom.basicblock import IRLiteral
from vyper.venom.function import IRFunction, IRLabel, IRBasicBlock


def test_multi_entry_block():
    ctx = IRFunction()

    finish_label = IRLabel("finish")
    target_label = IRLabel("target")
    block_1_label = IRLabel("block_1", ctx)

    op = ctx.append_instruction("store", [IRLiteral(10)])
    sum = ctx.append_instruction("add", [op, op])
    ctx.append_instruction("jnz", [sum, finish_label, block_1_label], False)

    target_bb = IRBasicBlock(block_1_label, ctx)
    ctx.append_basic_block(target_bb)
    sum = ctx.append_instruction("add", [sum, op])
    op = ctx.append_instruction("store", [IRLiteral(10)])
    ctx.append_instruction("mstore", [sum, op], False)
    ctx.append_instruction("jnz", [sum, target_label, finish_label])

    target_bb = IRBasicBlock(target_label, ctx)
    ctx.append_basic_block(target_bb)
    mul = ctx.append_instruction("mul", [sum, sum])
    ctx.append_instruction("jmp", [finish_label], False)

    finish_label = IRBasicBlock(finish_label, ctx)
    ctx.append_basic_block(finish_label)
    ctx.append_instruction("stop", [], False)

    asm = generate_assembly_experimental(ctx, OptimizationLevel.CODESIZE)

    print(ctx)
    print(asm)


if __name__ == "__main__":
    test_multi_entry_block()

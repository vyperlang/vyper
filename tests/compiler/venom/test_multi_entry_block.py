from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental
from vyper.venom.basicblock import IRLiteral
from vyper.venom.function import IRFunction, IRLabel, IRBasicBlock
from vyper.venom.passes.normalization import Normalization


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
    ctx.append_instruction("jnz", [sum, finish_label, target_label], False)

    target_bb = IRBasicBlock(target_label, ctx)
    ctx.append_basic_block(target_bb)
    mul = ctx.append_instruction("mul", [sum, sum])
    ctx.append_instruction("jmp", [finish_label], False)

    finish_bb = IRBasicBlock(finish_label, ctx)
    ctx.append_basic_block(finish_bb)
    ctx.append_instruction("stop", [], False)

    assert ctx.cfg_dirty == True, "CFG should be dirty"

    Normalization.run_pass(ctx)

    assert ctx.cfg_dirty == False, "CFG should be clean"
    assert ctx.normalized == True, "CFG should be normalized"

    finish_bb = ctx.get_basic_block(finish_label.value)
    cfg_in = list(finish_bb.cfg_in.keys())
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "finish_split_global", "Should contain finish_split_global"
    assert cfg_in[2].label.value == "finish_split_block_1", "Should contain finish_split_block_1"

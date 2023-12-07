from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRLiteral
from vyper.venom.function import IRBasicBlock, IRFunction, IRLabel
from vyper.venom.passes.normalization import NormalizationPass


def test_multi_entry_block_1():
    ctx = IRFunction()

    finish_label = IRLabel("finish")
    target_label = IRLabel("target")
    block_1_label = IRLabel("block_1", ctx)

    op = ctx.append_instruction("store", [IRLiteral(10)])
    acc = ctx.append_instruction("add", [op, op])
    ctx.append_instruction("jnz", [acc, finish_label, block_1_label], False)

    block_1 = IRBasicBlock(block_1_label, ctx)
    ctx.append_basic_block(block_1)
    acc = ctx.append_instruction("add", [acc, op])
    op = ctx.append_instruction("store", [IRLiteral(10)])
    ctx.append_instruction("mstore", [acc, op], False)
    ctx.append_instruction("jnz", [acc, finish_label, target_label], False)

    target_bb = IRBasicBlock(target_label, ctx)
    ctx.append_basic_block(target_bb)
    ctx.append_instruction("mul", [acc, acc])
    ctx.append_instruction("jmp", [finish_label], False)

    finish_bb = IRBasicBlock(finish_label, ctx)
    ctx.append_basic_block(finish_bb)
    ctx.append_instruction("stop", [], False)

    calculate_cfg(ctx)
    assert not ctx.normalized, "CFG should not be normalized"

    NormalizationPass.run_pass(ctx)

    assert ctx.normalized, "CFG should be normalized"

    finish_bb = ctx.get_basic_block(finish_label.value)
    cfg_in = list(finish_bb.cfg_in.keys())
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "finish_split_global", "Should contain finish_split_global"
    assert cfg_in[2].label.value == "finish_split_block_1", "Should contain finish_split_block_1"


# more complicated one
def test_multi_entry_block_2():
    ctx = IRFunction()

    finish_label = IRLabel("finish")
    target_label = IRLabel("target")
    block_1_label = IRLabel("block_1", ctx)
    block_2_label = IRLabel("block_2", ctx)

    op = ctx.append_instruction("store", [IRLiteral(10)])
    acc = ctx.append_instruction("add", [op, op])
    ctx.append_instruction("jnz", [acc, finish_label, block_1_label], False)

    block_1 = IRBasicBlock(block_1_label, ctx)
    ctx.append_basic_block(block_1)
    acc = ctx.append_instruction("add", [acc, op])
    op = ctx.append_instruction("store", [IRLiteral(10)])
    ctx.append_instruction("mstore", [acc, op], False)
    ctx.append_instruction("jnz", [acc, target_label, finish_label], False)

    block_2 = IRBasicBlock(block_2_label, ctx)
    ctx.append_basic_block(block_2)
    acc = ctx.append_instruction("add", [acc, op])
    op = ctx.append_instruction("store", [IRLiteral(10)])
    ctx.append_instruction("mstore", [acc, op], False)
    # switch the order of the labels, for fun
    ctx.append_instruction("jnz", [acc, finish_label, target_label], False)

    target_bb = IRBasicBlock(target_label, ctx)
    ctx.append_basic_block(target_bb)
    ctx.append_instruction("mul", [acc, acc])
    ctx.append_instruction("jmp", [finish_label], False)

    finish_bb = IRBasicBlock(finish_label, ctx)
    ctx.append_basic_block(finish_bb)
    ctx.append_instruction("stop", [], False)

    calculate_cfg(ctx)
    assert not ctx.normalized, "CFG should not be normalized"

    NormalizationPass.run_pass(ctx)

    assert ctx.normalized, "CFG should be normalized"

    finish_bb = ctx.get_basic_block(finish_label.value)
    cfg_in = list(finish_bb.cfg_in.keys())
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "finish_split_global", "Should contain finish_split_global"
    assert cfg_in[2].label.value == "finish_split_block_1", "Should contain finish_split_block_1"

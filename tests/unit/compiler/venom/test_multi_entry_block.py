from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.context import IRContext
from vyper.venom.function import IRBasicBlock, IRLabel
from vyper.venom.passes.normalization import NormalizationPass


def test_multi_entry_block_1():
    ctx = IRContext()
    fn = ctx.create_function("__global")

    finish_label = IRLabel("finish")
    target_label = IRLabel("target")
    block_1_label = IRLabel("block_1", fn)

    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    acc = bb.append_instruction("add", op, op)
    bb.append_instruction("jnz", acc, finish_label, block_1_label)

    block_1 = IRBasicBlock(block_1_label, fn)
    fn.append_basic_block(block_1)
    acc = block_1.append_instruction("add", acc, op)
    op = block_1.append_instruction("store", 10)
    block_1.append_instruction("mstore", acc, op)
    block_1.append_instruction("jnz", acc, finish_label, target_label)

    target_bb = IRBasicBlock(target_label, fn)
    fn.append_basic_block(target_bb)
    target_bb.append_instruction("mul", acc, acc)
    target_bb.append_instruction("jmp", finish_label)

    finish_bb = IRBasicBlock(finish_label, fn)
    fn.append_basic_block(finish_bb)
    finish_bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    ac.request_analysis(CFGAnalysis)
    assert not fn.normalized, "CFG should not be normalized"

    NormalizationPass(ac, fn).run_pass()

    assert fn.normalized, "CFG should be normalized"

    finish_bb = fn.get_basic_block(finish_label.value)
    cfg_in = list(finish_bb.cfg_in)
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "__global_split_finish", "Should contain __global_split_finish"
    assert cfg_in[2].label.value == "block_1_split_finish", "Should contain block_1_split_finish"


# more complicated one
def test_multi_entry_block_2():
    ctx = IRContext()
    fn = ctx.create_function("__global")

    finish_label = IRLabel("finish")
    target_label = IRLabel("target")
    block_1_label = IRLabel("block_1", fn)
    block_2_label = IRLabel("block_2", fn)

    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    acc = bb.append_instruction("add", op, op)
    bb.append_instruction("jnz", acc, finish_label, block_1_label)

    block_1 = IRBasicBlock(block_1_label, fn)
    fn.append_basic_block(block_1)
    acc = block_1.append_instruction("add", acc, op)
    op = block_1.append_instruction("store", 10)
    block_1.append_instruction("mstore", acc, op)
    block_1.append_instruction("jnz", acc, target_label, finish_label)

    block_2 = IRBasicBlock(block_2_label, fn)
    fn.append_basic_block(block_2)
    acc = block_2.append_instruction("add", acc, op)
    op = block_2.append_instruction("store", 10)
    block_2.append_instruction("mstore", acc, op)
    # switch the order of the labels, for fun and profit
    block_2.append_instruction("jnz", acc, finish_label, target_label)

    target_bb = IRBasicBlock(target_label, fn)
    fn.append_basic_block(target_bb)
    target_bb.append_instruction("mul", acc, acc)
    target_bb.append_instruction("jmp", finish_label)

    finish_bb = IRBasicBlock(finish_label, fn)
    fn.append_basic_block(finish_bb)
    finish_bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    ac.request_analysis(CFGAnalysis)
    assert not fn.normalized, "CFG should not be normalized"

    NormalizationPass(ac, fn).run_pass()

    assert fn.normalized, "CFG should be normalized"

    finish_bb = fn.get_basic_block(finish_label.value)
    cfg_in = list(finish_bb.cfg_in)
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "__global_split_finish", "Should contain __global_split_finish"
    assert cfg_in[2].label.value == "block_1_split_finish", "Should contain block_1_split_finish"


def test_multi_entry_block_with_dynamic_jump():
    ctx = IRContext()
    fn = ctx.create_function("__global")

    finish_label = IRLabel("finish")
    target_label = IRLabel("target")
    block_1_label = IRLabel("block_1", fn)

    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    acc = bb.append_instruction("add", op, op)
    bb.append_instruction("djmp", acc, finish_label, block_1_label)

    block_1 = IRBasicBlock(block_1_label, fn)
    fn.append_basic_block(block_1)
    acc = block_1.append_instruction("add", acc, op)
    op = block_1.append_instruction("store", 10)
    block_1.append_instruction("mstore", acc, op)
    block_1.append_instruction("jnz", acc, finish_label, target_label)

    target_bb = IRBasicBlock(target_label, fn)
    fn.append_basic_block(target_bb)
    target_bb.append_instruction("mul", acc, acc)
    target_bb.append_instruction("jmp", finish_label)

    finish_bb = IRBasicBlock(finish_label, fn)
    fn.append_basic_block(finish_bb)
    finish_bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    ac.request_analysis(CFGAnalysis)
    assert not fn.normalized, "CFG should not be normalized"

    NormalizationPass(ac, fn).run_pass()
    assert fn.normalized, "CFG should be normalized"

    finish_bb = fn.get_basic_block(finish_label.value)
    cfg_in = list(finish_bb.cfg_in)
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "__global_split_finish", "Should contain __global_split_finish"
    assert cfg_in[2].label.value == "block_1_split_finish", "Should contain block_1_split_finish"

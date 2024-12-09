from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.passes import RemoveUnusedVariablesPass


def test_removeunused_msize_basic():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mload", 32)
    msize = bb.append_instruction("msize")
    bb.append_instruction("mload", 64)
    bb.append_instruction("return", msize)

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mload"
    assert bb.instructions[0].operands[0].value == 32
    assert bb.instructions[1].opcode == "msize"
    assert bb.instructions[2].opcode == "return"


def test_removeunused_msize_two_msizes():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mload", 32)
    msize1 = bb.append_instruction("msize")
    bb.append_instruction("mload", 64)
    msize2 = bb.append_instruction("msize")
    bb.append_instruction("return", msize1, msize2)

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mload"
    assert bb.instructions[0].operands[0].value == 32
    assert bb.instructions[1].opcode == "msize"
    assert bb.instructions[2].opcode == "mload"
    assert bb.instructions[2].operands[0].value == 64
    assert bb.instructions[3].opcode == "msize"
    assert bb.instructions[4].opcode == "return"


def test_removeunused_msize_loop():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    msize = bb.append_instruction("msize")
    bb.append_instruction("mload", msize)
    bb.append_instruction("jmp", bb.label)

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "msize"
    assert bb.instructions[1].opcode == "mload"
    assert bb.instructions[1].operands[0] == msize
    assert bb.instructions[2].opcode == "jmp"


# Should this work?
def test_removeunused_unused_msize_loop():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("msize")
    bb.append_instruction("mload", 10)
    bb.append_instruction("jmp", bb.label)

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "jmp"


# Should this work?
def test_removeunused_unused_msize():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mload", 10)
    bb.append_instruction("msize")
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "stop", bb


def test_removeunused_basic():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    var1 = bb.append_instruction("add", 10, 20)
    bb.append_instruction("add", var1, 10)
    bb.append_instruction("mstore", var1, 20)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "add"
    assert bb.instructions[0].operands[0].value == 10
    assert bb.instructions[0].operands[1].value == 20
    assert bb.instructions[1].opcode == "mstore"
    assert bb.instructions[1].operands[0] == var1
    assert bb.instructions[1].operands[1].value == 20
    assert bb.instructions[2].opcode == "stop"


def test_removeunused_loop():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    after_bb = IRBasicBlock(IRLabel("after"), fn)
    fn.append_basic_block(after_bb)

    var1 = bb.append_instruction("store", 10)
    bb.append_instruction("jmp", after_bb.label)

    var2 = fn.get_next_variable()
    var_phi = after_bb.append_instruction("phi", bb.label, var1, after_bb.label, var2)
    after_bb.append_instruction("add", var_phi, 1, ret=var2)
    after_bb.append_instruction("add", var2, var_phi)
    after_bb.append_instruction("mstore", var2, 10)
    after_bb.append_instruction("jmp", after_bb.label)

    ac = IRAnalysesCache(fn)
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "store"
    assert bb.instructions[0].operands[0].value == 10
    assert bb.instructions[1].opcode == "jmp"

    assert after_bb.instructions[0].opcode == "phi"
    assert after_bb.instructions[1].opcode == "add"
    assert after_bb.instructions[1].operands[0] == var_phi
    assert after_bb.instructions[1].operands[1].value == 1
    assert after_bb.instructions[2].opcode == "mstore"
    assert after_bb.instructions[2].operands[0] == var2
    assert after_bb.instructions[2].operands[1].value == 10
    assert after_bb.instructions[3].opcode == "jmp"
    assert after_bb.instructions[3].operands[0] == after_bb.label

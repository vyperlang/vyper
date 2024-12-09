from vyper.venom.analysis.analysis import IRAnalysesCache
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

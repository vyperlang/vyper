from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes.load_elimination import LoadElimination


def test_simple_load_elimination():
    ctx = IRContext()
    fn = ctx.create_function("test")

    bb = fn.get_basic_block()

    ptr = IRLiteral(11)
    bb.append_instruction("mload", ptr)
    bb.append_instruction("mload", ptr)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    LoadElimination(ac, fn).run_pass()

    assert len([inst for inst in bb.instructions if inst.opcode == "mload"]) == 1

    inst0, inst1, inst2 = bb.instructions

    assert inst0.opcode == "mload"
    assert inst1.opcode == "store"
    assert inst1.operands[0] == inst0.output
    assert inst2.opcode == "stop"


def test_equivalent_var_elimination():
    ctx = IRContext()
    fn = ctx.create_function("test")

    bb = fn.get_basic_block()

    ptr1 = bb.append_instruction("store", IRLiteral(11))
    ptr2 = bb.append_instruction("store", ptr1)
    bb.append_instruction("mload", ptr1)
    bb.append_instruction("mload", ptr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    LoadElimination(ac, fn).run_pass()

    assert len([inst for inst in bb.instructions if inst.opcode == "mload"]) == 1

    inst0, inst1, inst2, inst3, inst4 = bb.instructions

    assert inst0.opcode == "store"
    assert inst1.opcode == "store"
    assert inst2.opcode == "mload"
    assert inst2.operands[0] == inst0.output
    assert inst3.opcode == "store"
    assert inst3.operands[0] == inst2.output
    assert inst4.opcode == "stop"


def test_elimination_barrier():
    ctx = IRContext()
    fn = ctx.create_function("test")

    bb = fn.get_basic_block()

    ptr = IRLiteral(11)
    bb.append_instruction("mload", ptr)

    arbitrary = IRVariable("%100")
    # fence, writes to memory
    bb.append_instruction("staticcall", arbitrary, arbitrary, arbitrary, arbitrary)

    bb.append_instruction("mload", ptr)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    instructions = bb.instructions.copy()
    LoadElimination(ac, fn).run_pass()

    assert instructions == bb.instructions  # no change


def test_store_load_elimination():
    ctx = IRContext()
    fn = ctx.create_function("test")

    bb = fn.get_basic_block()

    val = IRLiteral(55)
    ptr1 = bb.append_instruction("store", IRLiteral(11))
    ptr2 = bb.append_instruction("store", ptr1)
    bb.append_instruction("mstore", val, ptr1)
    bb.append_instruction("mload", ptr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    LoadElimination(ac, fn).run_pass()

    assert len([inst for inst in bb.instructions if inst.opcode == "mload"]) == 0

    inst0, inst1, inst2, inst3, inst4 = bb.instructions

    assert inst0.opcode == "store"
    assert inst1.opcode == "store"
    assert inst2.opcode == "mstore"
    assert inst3.opcode == "store"
    assert inst3.operands[0] == inst2.operands[0]
    assert inst4.opcode == "stop"


def test_store_load_barrier():
    ctx = IRContext()
    fn = ctx.create_function("test")

    bb = fn.get_basic_block()

    val = IRLiteral(55)
    ptr1 = bb.append_instruction("store", IRLiteral(11))
    ptr2 = bb.append_instruction("store", ptr1)
    bb.append_instruction("mstore", val, ptr1)

    arbitrary = IRVariable("%100")
    # fence, writes to memory
    bb.append_instruction("staticcall", arbitrary, arbitrary, arbitrary, arbitrary)

    bb.append_instruction("mload", ptr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    instructions = bb.instructions.copy()
    LoadElimination(ac, fn).run_pass()

    assert instructions == bb.instructions

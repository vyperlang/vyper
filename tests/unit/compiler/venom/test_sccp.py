import pytest

from vyper.exceptions import StaticAssertionException
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.sccp import SCCP
from vyper.venom.passes.sccp.sccp import LatticeEnum


def test_simple_case():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", 32)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("return", p1, op3)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    sccp.run_pass()

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96


def test_branch_eliminator_simple():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb1 = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    br1.append_instruction("stop")
    br2 = IRBasicBlock(IRLabel("else"), fn)
    br2.append_instruction("jmp", IRLabel("foo"))

    fn.append_basic_block(br1)
    fn.append_basic_block(br2)

    bb1.append_instruction("jnz", IRLiteral(1), br1.label, br2.label)

    bb2 = IRBasicBlock(IRLabel("foo"), fn)
    bb2.append_instruction("jnz", IRLiteral(0), br1.label, br2.label)
    fn.append_basic_block(bb2)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    sccp.run_pass()

    assert bb1.instructions[-1].opcode == "jmp"
    assert bb1.instructions[-1].operands == [br1.label]
    assert bb2.instructions[-1].opcode == "jmp"
    assert bb2.instructions[-1].operands == [br2.label]


def test_assert_elimination():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction("assert", IRLiteral(1))
    bb.append_instruction("assert_unreachable", IRLiteral(1))
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    sccp.run_pass()

    for inst in bb.instructions[:-1]:
        assert inst.opcode == "nop"


@pytest.mark.parametrize("asserter", ("assert", "assert_unreachable"))
def test_assert_false(asserter):
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction(asserter, IRLiteral(0))
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    with pytest.raises(StaticAssertionException):
        sccp.run_pass()


def test_cont_jump_case():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", 32)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("jnz", op3, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    sccp.run_pass()

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5")].value == 106
    assert sccp.lattice.get(IRVariable("%6")) == LatticeEnum.BOTTOM


def test_cont_phi_case():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)
    join = IRBasicBlock(IRLabel("join"), fn)
    fn.append_basic_block(join)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", 32)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("jnz", op3, br1.label, br2.label)

    op4 = br1.append_instruction("add", op3, 10)
    br1.append_instruction("jmp", join.label)
    br2.append_instruction("add", op3, p1, ret=op4)
    br2.append_instruction("jmp", join.label)

    join.append_instruction("return", op4, p1)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    sccp.run_pass()

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%5")].value == 2


def test_cont_phi_const_case():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)
    join = IRBasicBlock(IRLabel("join"), fn)
    fn.append_basic_block(join)

    p1 = bb.append_instruction("store", 1)
    op1 = bb.append_instruction("store", 32)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("jnz", op3, br1.label, br2.label)

    op4 = br1.append_instruction("add", op3, 10)
    br1.append_instruction("jmp", join.label)
    br2.append_instruction("add", op3, p1, ret=op4)
    br2.append_instruction("jmp", join.label)

    join.append_instruction("return", op4, p1)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    sccp = SCCP(ac, fn)
    sccp.run_pass()

    assert sccp.lattice[IRVariable("%1")].value == 1
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)].value == 97
    assert sccp.lattice[IRVariable("%5")].value == 2

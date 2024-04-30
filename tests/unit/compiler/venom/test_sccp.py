from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.pass_manager import IRPassManager
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

    pm = IRPassManager(fn)
    MakeSSA(pm).run_pass()
    sccp = SCCP(pm)
    sccp.run_pass()

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96


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

    pm = IRPassManager(fn)
    MakeSSA(pm).run_pass()
    sccp = SCCP(pm)
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

    pm = IRPassManager(fn)
    MakeSSA(pm).run_pass()
    sccp = SCCP(pm)
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

    pm = IRPassManager(fn)
    MakeSSA(pm).run_pass()
    sccp = SCCP(pm)
    sccp.run_pass()

    assert sccp.lattice[IRVariable("%1")].value == 1
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)].value == 97
    assert sccp.lattice[IRVariable("%5")].value == 2

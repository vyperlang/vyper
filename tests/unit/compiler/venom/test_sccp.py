from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.sccp import SCCP, LatticeEnum


def test_simple_case():
    ctx = IRFunction(IRLabel("_global"))

    bb = ctx.get_basic_block()
    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("push", 32)
    op2 = bb.append_instruction("push", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("return", p1, op3)

    make_ssa_pass = MakeSSA()
    make_ssa_pass.run_pass(ctx, ctx.basic_blocks[0])
    sccp = SCCP(make_ssa_pass.dom)
    sccp.run_pass(ctx, ctx.basic_blocks[0])

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96


def test_cont_jump_case():
    ctx = IRFunction(IRLabel("_global"))

    bb = ctx.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), ctx)
    ctx.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), ctx)
    ctx.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("push", 32)
    op2 = bb.append_instruction("push", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("jnz", op3, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    make_ssa_pass = MakeSSA()
    make_ssa_pass.run_pass(ctx, ctx.basic_blocks[0])
    sccp = SCCP(make_ssa_pass.dom)
    sccp.run_pass(ctx, ctx.basic_blocks[0])

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5")].value == 106
    assert sccp.lattice[IRVariable("%6")] == LatticeEnum.BOTTOM


def test_cont_phi_case():
    ctx = IRFunction(IRLabel("_global"))

    bb = ctx.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), ctx)
    ctx.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), ctx)
    ctx.append_basic_block(br2)
    join = IRBasicBlock(IRLabel("join"), ctx)
    ctx.append_basic_block(join)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("push", 32)
    op2 = bb.append_instruction("push", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("jnz", op3, br1.label, br2.label)

    op4 = br1.append_instruction("add", op3, 10)
    br1.append_instruction("jmp", join.label)
    op5 = br2.append_instruction("add", op3, p1, ret=op4)
    br2.append_instruction("jmp", join.label)

    join.append_instruction("return", op4, p1)

    make_ssa_pass = MakeSSA()
    make_ssa_pass.run_pass(ctx, ctx.basic_blocks[0])
    sccp = SCCP(make_ssa_pass.dom)
    sccp.run_pass(ctx, ctx.basic_blocks[0])

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%5")] == LatticeEnum.TOP


def test_cont_phi_const_case():
    ctx = IRFunction(IRLabel("_global"))

    bb = ctx.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), ctx)
    ctx.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), ctx)
    ctx.append_basic_block(br2)
    join = IRBasicBlock(IRLabel("join"), ctx)
    ctx.append_basic_block(join)

    p1 = bb.append_instruction("push", 1)
    op1 = bb.append_instruction("push", 32)
    op2 = bb.append_instruction("push", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("jnz", op3, br1.label, br2.label)

    op4 = br1.append_instruction("add", op3, 10)
    br1.append_instruction("jmp", join.label)
    op5 = br2.append_instruction("add", op3, p1, ret=op4)
    br2.append_instruction("jmp", join.label)

    join.append_instruction("return", op4, p1)

    make_ssa_pass = MakeSSA()
    make_ssa_pass.run_pass(ctx, ctx.basic_blocks[0])
    sccp = SCCP(make_ssa_pass.dom)
    sccp.run_pass(ctx, ctx.basic_blocks[0])

    assert sccp.lattice[IRVariable("%1")].value == 1
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)].value == 97
    assert sccp.lattice[IRVariable("%5")] == LatticeEnum.TOP


# if __name__ == "__main__":
#     test_cont_phi_const_case()

import pytest

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.exceptions import StaticAssertionException
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes import SCCP, MakeSSA
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
    bb.append_instruction("jnz", p1, br1.label, br2.label)

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
    bb.append_instruction("jnz", p1, br1.label, br2.label)

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
    assert sccp.lattice[IRVariable("%5", version=2)].value == 106
    assert sccp.lattice[IRVariable("%5", version=1)] == LatticeEnum.BOTTOM
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
    assert sccp.lattice[IRVariable("%5", version=1)].value == 97
    assert sccp.lattice[IRVariable("%5", version=2)].value == 106
    assert sccp.lattice[IRVariable("%5")] == LatticeEnum.BOTTOM


def test_phi_reduction_after_unreachable_block():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    join = IRBasicBlock(IRLabel("join"), fn)
    fn.append_basic_block(join)

    op = bb.append_instruction("store", 1)
    true = IRLiteral(1)
    bb.append_instruction("jnz", true, br1.label, join.label)

    op1 = br1.append_instruction("store", 2)

    br1.append_instruction("jmp", join.label)

    join.append_instruction("phi", bb.label, op, br1.label, op1)
    join.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()

    assert join.instructions[0].opcode == "store", join.instructions[0]
    assert join.instructions[0].operands == [op1]

    assert join.instructions[1].opcode == "stop"


def test_sccp_offsets_opt():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", 32)
    op2 = bb.append_instruction("add", 0, IRLabel("mem"))
    op3 = bb.append_instruction("store", 64)
    bb.append_instruction("dloadbytes", op1, op2, op3)
    op5 = bb.append_instruction("mload", op3)
    op6 = bb.append_instruction("iszero", op5)
    bb.append_instruction("jnz", op6, br1.label, br2.label)

    op01 = br1.append_instruction("store", 32)
    op02 = br1.append_instruction("add", 0, IRLabel("mem"))
    op03 = br1.append_instruction("store", 64)
    br1.append_instruction("dloadbytes", op01, op02, op03)
    op05 = br1.append_instruction("mload", op03)
    op06 = br1.append_instruction("iszero", op05)
    br1.append_instruction("return", p1, op06)

    op11 = br2.append_instruction("store", 32)
    op12 = br2.append_instruction("add", 0, IRLabel("mem"))
    op13 = br2.append_instruction("store", 64)
    br2.append_instruction("dloadbytes", op11, op12, op13)
    op15 = br2.append_instruction("mload", op13)
    op16 = br2.append_instruction("iszero", op15)
    br2.append_instruction("return", p1, op16)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    SCCP(ac, fn).run_pass()
    # RemoveUnusedVariablesPass(ac, fn).run_pass()

    offset_count = 0
    for bb in fn.get_basic_blocks():
        for instruction in bb.instructions:
            assert instruction.opcode != "add"
            if instruction.opcode == "offset":
                offset_count += 1

    assert offset_count == 3


venom_progs = [
    (
        """
    _global:
        %par = param
        %1 = sub %par, %par
        %2 = xor %par, %par
        return %1, %2
    """,
        """
    _global:
        %par = param
        %1 = store 0
        %2 = store 0
        return 0, 0
    """,
    ),
    (
        """
    _global:
        %par = param
        %1 = sub %par, 0
        %2 = xor %par, 0
        %3 = add 0, %par
        %4 = sub 0, %par
        return %1, %2, %3, %4
    """,
        """
    _global:
        %par = param
        %1 = %par
        %2 = %par
        %3 = %par
        %4 = sub 0, %par
        return %1, %2, %3, %4
    """,
    ),
    (
        """
    _global:
        %par = param
        %1 = xor 115792089237316195423570985008687907853269984665640564039457584007913129639935, %par
        return %1
    """,
        """
    _global:
        %par = param
        %1 = not %par
        return %1
    """,
    ),
    (
        """
    _global:
        %par = param
        %1 = shl 0, %par
        %2 = shr 0, %1
        %3 = sar 0, %2
        return %1, %2, %3
    """,
        """
    _global:
        %par = param
        %1 = %par
        %2 = %1
        %3 = %2
        return %1, %2, %3
    """,
    ),
    (
        """
    _global:
        %par = param
        %1_1 = mul 0, %par
        %1_2 = mul %par, 0
        %2_1 = div 0, %par
        %2_2 = div %par, 0
        %3_1 = sdiv 0, %par
        %3_2 = sdiv %par, 0
        %4_1 = mod 0, %par
        %4_2 = mod %par, 0
        %5_1 = smod 0, %par
        %5_2 = smod %par, 0
        %6_1 = and 0, %par
        %6_2 = and %par, 0
        return %1_1, %1_2, %2_1, %2_2, %3_1, %3_2, %4_1, %4_2, %5_1, %5_2, %6_1, %6_2
    """,
        """
    _global:
        %par = param
        %1_1 = 0
        %1_2 = 0
        %2_1 = div 0, %par
        %2_2 = 0
        %3_1 = sdiv 0, %par
        %3_2 = 0
        %4_1 = mod 0, %par
        %4_2 = 0
        %5_1 = smod 0, %par
        %5_2 = 0
        %6_1 = 0
        %6_2 = 0
        return 0, 0, %2_1, 0, %3_1, 0, %4_1, 0, %5_1, 0, 0, 0
    """,
    ),
]


@pytest.mark.parametrize("correct_transformation", venom_progs)
def test_sccp_binopt(correct_transformation):
    pre, post = correct_transformation

    ctx = parse_from_basic_block(pre)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        SCCP(ac, fn).run_pass()

    print(ctx)

    assert_ctx_eq(ctx, parse_from_basic_block(post))

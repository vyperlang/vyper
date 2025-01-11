import pytest

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.exceptions import StaticAssertionException
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes import (
    SCCP,
    AlgebraicOptimizationPass,
    MakeSSA,
    RemoveUnusedVariablesPass,
    StoreElimination,
)
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
    AlgebraicOptimizationPass(ac, fn).run_pass()
    # RemoveUnusedVariablesPass(ac, fn).run_pass()

    offset_count = 0
    for bb in fn.get_basic_blocks():
        for instruction in bb.instructions:
            assert instruction.opcode != "add"
            if instruction.opcode == "offset":
                offset_count += 1

    assert offset_count == 3


# venom programs that
# should be optimized accordigly
# the comments before the test
# represents which optimizations
# does this program expects
venom_progs = [
    # x - x -> 0
    # x ^ x -> 0
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
        return 0, 0
    """,
    ),
    # x + 0 == x - 0 == x ^ 0 -> x
    # this cannot be done for 0 - x
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
        %4 = sub 0, %par
        return %par, %par, %par, %4
    """,
    ),
    # x ^ 0xFF..FF -> not x
    (
        """
    _global:
        %par = param
        %tmp = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %1 = xor %tmp, %par
        return %1
    """,
        """
    _global:
        %par = param
        %1 = not %par
        return %1
    """,
    ),
    # x << 0 == x >> 0 == x (sar) 0 -> x
    # sar is right arithmetic shift
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
        return %par, %par, %par
    """,
    ),
    # x * 0 == 0 * x == x / 0 == x % 0 == x & 0 == 0 & x -> 0
    # checks for non comutative ops
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
        %2_1 = div 0, %par
        %3_1 = sdiv 0, %par
        %4_1 = mod 0, %par
        %5_1 = smod 0, %par
        return 0, 0, %2_1, 0, %3_1, 0, %4_1, 0, %5_1, 0, 0, 0
    """,
    ),
    # x * 1 == 1 * x == x / 1 -> x
    # checks for non comutative ops
    (
        """
    _global:
        %par = param
        %1_1 = mul 1, %par
        %1_2 = mul %par, 1
        %2_1 = div 1, %par
        %2_2 = div %par, 1
        %3_1 = sdiv 1, %par
        %3_2 = sdiv %par, 1
        return %1_1, %1_2, %2_1, %2_2, %3_1, %3_2
    """,
        """
    _global:
        %par = param
        %2_1 = div 1, %par
        %3_1 = sdiv 1, %par
        return %par, %par, %2_1, %par, %3_1, %par
    """,
    ),
    # x % 1 -> 0
    (
        """
    _global:
        %par = param
        %1 = mod %par, 1
        %2 = smod %par, 1
        return %1, %2
    """,
        """
    _global:
        %par = param
        return 0, 0
    """,
    ),
    # x & 0xFF..FF == 0xFF..FF & x -> x
    (
        """
    _global:
        %par = param
        %tmp = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %1 = and %par, %tmp
        %2 = and %tmp, %par
        return %1, %2
    """,
        """
    _global:
        %par = param
        return %par, %par
    """,
    ),
    # x * 2**n -> x << n
    # x / 2**n -> x >> n
    (
        """
    _global:
        %par = param
        %1 = mod %par, 8
        %2 = mul %par, 16
        %3 = div %par, 4
        return %1, %2, %3
    """,
        """
    _global:
        %par = param
        %1 = and %par, 7
        %2 = shl 4, %par
        %3 = shr 2, %par
        return %1, %2, %3
    """,
    ),
    # x ** 0 == 1 ** x -> 1
    # x ** 1 -> x
    (
        """
    _global:
        %par = param
        %1 = exp %par, 0
        %2 = exp 1, %par
        %3 = exp 0, %par
        %4 = exp %par, 1
        return %1, %2, %3, %4
    """,
        """
    _global:
        %par = param
        %3 = iszero %par
        return 1, 1, %3, %par
    """,
    ),
    # x < x == x > x -> 0
    (
        """
    _global:
        %par = param
        %tmp = %par
        %1 = gt %tmp, %par
        %2 = sgt %tmp, %par
        %3 = lt %tmp, %par
        %4 = slt %tmp, %par
        return %1, %2, %3, %4
    """,
        """
    _global:
        %par = param
        return 0, 0, 0, 0
    """,
    ),
    # x | 0 -> x
    # x | 0xFF..FF -> 0xFF..FF
    # x = 0 == 0 = x -> iszero x
    # x = x -> 1
    (
        """
    _global:
        %par = param
        %1 = or %par, 0
        %tmp = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %2 = or %par, %tmp
        %3 = eq %par, 0
        %4 = eq 0, %par
        %tmp_par = %par
        %5 = eq %tmp_par, %par
        return %1, %2, %3, %4, %5
    """,
        """
    _global:
        %par = param
        %3 = iszero %par
        %4 = iszero %par
        return %par, 115792089237316195423570985008687907853269984665640564039457584007913129639935,
               %3, %4, 1
    """,
    ),
    # x == 1 -> iszero (x xor 1) if it is only used as boolean
    # x | (non zero) -> 1 if it is only used as boolean
    (
        """
    _global:
        %par = param
        %1 = eq %par, 1
        %2 = eq %par, 1
        assert %1
        %3 = or %par, 123
        %4 = or %par, 123
        assert %3
        return %2, %4
    """,
        """
    _global:
        %par = param
        %5 = xor %par, 1
        %1 = iszero %5
        %2 = eq %par, 1
        assert %1
        %4 = or %par, 123
        nop
        return %2, %4
    """,
    ),
    # unsigned x > 0xFF..FF == x < 0 -> 0
    # signed: x > MAX_SIGNED (0x3F..FF) == x < MIN_SIGNED (0xF0..00) -> 0
    (
        """
    _global:
        %par = param
        %tmp1 = -57896044618658097711785492504343953926634992332820282019728792003956564819968
        %1 = slt %par, %tmp1
        %tmp2 = 57896044618658097711785492504343953926634992332820282019728792003956564819967
        %2 = sgt %par, %tmp2
        %3 = lt %par, 0
        %tmp3 = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %4 = gt %par, %tmp3
        return %1, %2, %3, %4
    """,
        """
    _global:
        %par = param
        return 0, 0, 0, 0
    """,
    ),
]


@pytest.mark.parametrize("correct_transformation", venom_progs)
def test_sccp_binopt(correct_transformation):
    pre, post = correct_transformation

    ctx = parse_from_basic_block(pre)

    print(ctx)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        StoreElimination(ac, fn).run_pass()
        SCCP(ac, fn).run_pass()
        AlgebraicOptimizationPass(ac, fn).run_pass()
        SCCP(ac, fn).run_pass()
        StoreElimination(ac, fn).run_pass()
        RemoveUnusedVariablesPass(ac, fn).run_pass()

    print(ctx)

    assert_ctx_eq(ctx, parse_from_basic_block(post))

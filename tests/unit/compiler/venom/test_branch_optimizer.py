import pytest

from vyper.exceptions import StaticAssertionException
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes.branch_optimization import BranchOptimizationPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass


@pytest.mark.parametrize("iszero_count", range(10))
def test_simple_jump_case(iszero_count):
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", p1)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    jnz_input = op3
    for _ in range(iszero_count):
        jnz_input = bb.append_instruction("iszero", jnz_input)
    # op4 = bb.append_instruction("iszero", op3)
    bb.append_instruction("jnz", jnz_input, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    BranchOptimizationPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[-1].opcode == "jnz"
    assert bb.instructions[-1].operands[0] == op3
    if iszero_count % 2 == 0:
        assert bb.instructions[-1].operands[1] == br1.label
        assert bb.instructions[-1].operands[2] == br2.label
    else:
        assert bb.instructions[-1].operands[1] == br2.label
        assert bb.instructions[-1].operands[2] == br1.label


@pytest.mark.parametrize("interleave_point", range(1, 5))
def test_interleaved_jump_case(interleave_point):
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", p1)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    jnz_input = op3
    for _ in range(interleave_point):
        jnz_input = bb.append_instruction("iszero", jnz_input)
    bb.append_instruction("mstore", p1, jnz_input)
    for _ in range(5):
        jnz_input = bb.append_instruction("iszero", jnz_input)
    bb.append_instruction("jnz", jnz_input, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    print(ctx)
    BranchOptimizationPass(ac, fn).run_pass()

    RemoveUnusedVariablesPass(ac, fn).run_pass()
    print("-----------------")
    print(ctx)

    assert bb.instructions[-1].opcode == "jnz"
    assert bb.instructions[-1].operands[0] == op3
    if interleave_point % 2 == 0:
        assert bb.instructions[-1].operands[1] == br1.label
        assert bb.instructions[-1].operands[2] == br2.label
    else:
        assert bb.instructions[-1].operands[1] == br2.label
        assert bb.instructions[-1].operands[2] == br1.label


# if __name__ == '__main__':
#      test_simple_jump_case(3)

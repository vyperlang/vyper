import pytest

from vyper.exceptions import StaticAssertionException
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes.branch_optimization import BranchOptimizationPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass


def test_simple_jump_case():
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
    jnz_input = bb.append_instruction("iszero", op3)
    bb.append_instruction("jnz", jnz_input, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    BranchOptimizationPass(ac, fn).run_pass()

    assert bb.instructions[-1].opcode == "jnz"
    assert bb.instructions[-1].operands[0] == op3
    assert bb.instructions[-1].operands[1] == br2.label
    assert bb.instructions[-1].operands[2] == br1.label

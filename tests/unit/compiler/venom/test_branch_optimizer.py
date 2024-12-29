from vyper.venom.analysis import DFGAnalysis, IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.passes import BranchOptimizationPass, MakeSSA


def test_simple_jump_case():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    p2 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", p1)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    jnz_input = bb.append_instruction("iszero", op3)
    bb.append_instruction("jnz", jnz_input, br1.label, br2.label)

    br1.append_instruction("add", op3, p1)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p2)
    br2.append_instruction("stop")

    term_inst = bb.instructions[-1]

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()

    old_dfg = ac.request_analysis(DFGAnalysis)
    assert term_inst not in old_dfg.get_uses(op3), "jnz not using the old condition"
    assert term_inst in old_dfg.get_uses(jnz_input), "jnz using the new condition"

    BranchOptimizationPass(ac, fn).run_pass()

    # Test that the jnz targets are inverted and
    # the jnz condition updated
    assert term_inst.opcode == "jnz"
    assert term_inst.operands[0] == op3
    assert term_inst.operands[1] == br2.label
    assert term_inst.operands[2] == br1.label

    # Test that the dfg is updated correctly
    dfg = ac.request_analysis(DFGAnalysis)
    assert dfg is not old_dfg, "DFG should be invalidated by BranchOptimizationPass"
    assert term_inst in dfg.get_uses(op3), "jnz not using the new condition"
    assert term_inst not in dfg.get_uses(jnz_input), "jnz still using the old condition"

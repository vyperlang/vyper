from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral
from vyper.venom.context import IRContext
from vyper.venom.passes import SCCP, SimplifyCFGPass


def test_phi_reduction_after_block_pruning():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    join = IRBasicBlock(IRLabel("join"), fn)
    fn.append_basic_block(join)

    true = IRLiteral(1)
    bb.append_instruction("jnz", true, br1.label, br2.label)

    op1 = br1.append_instruction("store", 1)
    op2 = br2.append_instruction("store", 2)

    br1.append_instruction("jmp", join.label)
    br2.append_instruction("jmp", join.label)

    join.append_instruction("phi", br1.label, op1, br2.label, op2)
    join.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    SimplifyCFGPass(ac, fn).run_pass()

    bbs = list(fn.get_basic_blocks())

    assert len(bbs) == 1
    final_bb = bbs[0]

    inst0, inst1, inst2 = final_bb.instructions

    assert inst0.opcode == "store"
    assert inst0.operands == [IRLiteral(1)]
    assert inst1.opcode == "store"
    assert inst1.operands == [inst0.output]
    assert inst2.opcode == "stop"

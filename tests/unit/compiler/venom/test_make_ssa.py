from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.passes.make_ssa import MakeSSA


def test_phi_case():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb_cont = IRBasicBlock(IRLabel("condition"), fn)
    bb_then = IRBasicBlock(IRLabel("then"), fn)
    bb_else = IRBasicBlock(IRLabel("else"), fn)
    bb_if_exit = IRBasicBlock(IRLabel("if_exit"), fn)
    fn.append_basic_block(bb_cont)
    fn.append_basic_block(bb_then)
    fn.append_basic_block(bb_else)
    fn.append_basic_block(bb_if_exit)

    v = bb.append_instruction("mload", 64)
    bb_cont.append_instruction("jnz", v, bb_then.label, bb_else.label)

    bb_if_exit.append_instruction("add", v, 1, ret=v)
    bb_if_exit.append_instruction("jmp", bb_cont.label)

    bb_then.append_instruction("assert", bb_then.append_instruction("mload", 96))
    bb_then.append_instruction("jmp", bb_if_exit.label)
    bb_else.append_instruction("jmp", bb_if_exit.label)

    bb.append_instruction("jmp", bb_cont.label)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()

    condition_block = fn.get_basic_block("condition")
    assert len(condition_block.instructions) == 2

    phi_inst = condition_block.instructions[0]
    assert phi_inst.opcode == "phi"
    assert phi_inst.operands[0].name == "_global"
    assert phi_inst.operands[1].name == "%1"
    assert phi_inst.operands[2].name == "if_exit"
    assert phi_inst.operands[3].name == "%1"
    assert phi_inst.output.name == "%1"
    assert phi_inst.output.value != phi_inst.operands[1].value
    assert phi_inst.output.value != phi_inst.operands[3].value

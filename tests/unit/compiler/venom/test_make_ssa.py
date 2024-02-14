from vyper.venom.analysis import calculate_cfg, calculate_liveness
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.bb_optimizer import _optimize_unused_variables
from vyper.venom.function import IRFunction
from vyper.venom.passes.make_ssa import MakeSSA


def test_phi_case():
    ctx = IRFunction(IRLabel("_global"))

    bb = ctx.get_basic_block()

    bb_cont = IRBasicBlock(IRLabel("condition"), ctx)
    bb_then = IRBasicBlock(IRLabel("then"), ctx)
    bb_else = IRBasicBlock(IRLabel("else"), ctx)
    bb_if_exit = IRBasicBlock(IRLabel("if_exit"), ctx)
    ctx.append_basic_block(bb_cont)
    ctx.append_basic_block(bb_then)
    ctx.append_basic_block(bb_else)
    ctx.append_basic_block(bb_if_exit)

    v = bb.append_instruction("mload", 64)
    bb_cont.append_instruction("jnz", v, bb_then.label, bb_else.label)

    bb_if_exit.append_instruction("add", v, 1, ret=v)
    bb_if_exit.append_instruction("jmp", bb_cont.label)

    bb_then.append_instruction("assert", bb_then.append_instruction("mload", 96))
    bb_then.append_instruction("jmp", bb_if_exit.label)
    bb_else.append_instruction("jmp", bb_if_exit.label)

    bb.append_instruction("jmp", bb_cont.label)

    calculate_cfg(ctx)
    MakeSSA.run_pass(ctx, ctx.basic_blocks[0])
    calculate_liveness(ctx)
    # _optimize_unused_variables(ctx)
    # calculate_liveness(ctx)
    print(ctx.as_graph())


if __name__ == "__main__":
    test_phi_case()

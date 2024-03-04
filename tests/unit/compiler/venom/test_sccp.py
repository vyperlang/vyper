from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.function import IRFunction
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.sccp import SCCP


def test_simple_case():
    ctx = IRFunction(IRLabel("_global"))

    bb = ctx.get_basic_block()
    op1 = bb.append_instruction("push", 32)
    op2 = bb.append_instruction("push", 64)
    op3 = bb.append_instruction("add", op1, op2)
    bb.append_instruction("return", 32, op3)

    make_ssa_pass = MakeSSA()
    make_ssa_pass.run_pass(ctx, ctx.basic_blocks[0])
    SCCP(make_ssa_pass.dom).run_pass(ctx, ctx.basic_blocks[0])

    print(ctx.as_graph())


if __name__ == "__main__":
    test_simple_case()

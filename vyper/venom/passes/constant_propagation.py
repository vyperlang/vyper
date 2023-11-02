from vyper.utils import ir_pass
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.function import IRFunction


def _process_basic_block(ctx: IRFunction, bb: IRBasicBlock):
    pass


@ir_pass
def ir_pass_constant_propagation(ctx: IRFunction):
    for bb in ctx.basic_blocks:
        _process_basic_block(ctx, bb)

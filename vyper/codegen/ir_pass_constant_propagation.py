from vyper.codegen.ir_basicblock import IRBasicBlock
from vyper.codegen.ir_function import IRFunction
from vyper.utils import OrderedSet, ir_pass


def _process_basic_block(ctx: IRFunction, bb: IRBasicBlock):
    pass


@ir_pass
def ir_pass_constant_propagation(ctx: IRFunction):
    for bb in ctx.basic_blocks:
        _process_basic_block(ctx, bb)

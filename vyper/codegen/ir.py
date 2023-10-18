from typing import Optional
from vyper.codegen.ir_pass_constant_propagation import ir_pass_constant_propagation
from vyper.codegen.dfg import convert_ir_to_dfg
from vyper.codegen.ir_function import IRFunctionBase
from vyper.codegen.ir_node import IRnode
from vyper.codegen.ir_pass_dft import ir_pass_dft
from vyper.compiler.settings import OptimizationLevel
from vyper.ir.bb_optimizer import (
    calculate_in_set,
    calculate_liveness,
    optimize_empty_blocks,
    optimize_function,
)
from vyper.ir.ir_to_bb_pass import convert_ir_basicblock


def generate_ir(ir: IRnode, optimize: Optional[OptimizationLevel] = None) -> IRFunctionBase:
    # Convert "old" IR to "new" IR
    ctx = convert_ir_basicblock(ir, optimize)

    # Run passes on "new" IR
    if optimize is not OptimizationLevel.NONE:
        optimize_function(ctx)

    optimize_empty_blocks(ctx)
    calculate_in_set(ctx)
    calculate_liveness(ctx)
    convert_ir_to_dfg(ctx)

    ir_pass_constant_propagation(ctx)
    ir_pass_dft(ctx)

    calculate_in_set(ctx)
    calculate_liveness(ctx)

    convert_ir_to_dfg(ctx)

    return ctx

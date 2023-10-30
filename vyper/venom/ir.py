from typing import Optional

from vyper.venom.dfg import convert_ir_to_dfg
from vyper.venom.ir_function import IRFunction
from vyper.codegen.ir_node import IRnode
from vyper.venom.ir_pass_constant_propagation import ir_pass_constant_propagation
from vyper.compiler.settings import OptimizationLevel
from vyper.ir.bb_optimizer import (
    calculate_cfg_in,
    calculate_liveness,
    ir_pass_optimize_empty_blocks,
    ir_pass_optimize_unused_variables,
    ir_pass_remove_unreachable_blocks,
)
from vyper.ir.ir_to_bb_pass import convert_ir_basicblock


def generate_ir(ir: IRnode, optimize: Optional[OptimizationLevel] = None) -> IRFunction:
    # Convert "old" IR to "new" IR
    ctx = convert_ir_basicblock(ir)

    # Run passes on "new" IR
    # TODO: Add support for optimization levels
    while True:
        changes = 0

        changes += ir_pass_optimize_empty_blocks(ctx)
        changes += ir_pass_remove_unreachable_blocks(ctx)

        calculate_liveness(ctx)

        changes += ir_pass_optimize_unused_variables(ctx)

        calculate_cfg_in(ctx)
        calculate_liveness(ctx)
        convert_ir_to_dfg(ctx)

        changes += ir_pass_constant_propagation(ctx)
        # changes += ir_pass_dft(ctx)

        calculate_cfg_in(ctx)
        calculate_liveness(ctx)
        convert_ir_to_dfg(ctx)

        if changes == 0:
            break

    return ctx

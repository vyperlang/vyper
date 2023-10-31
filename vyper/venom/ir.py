# REVIEW: maybe this should be __init__.py (or some name less generic than 'ir.py')
from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom.bb_optimizer import (
    calculate_cfg_in,
    calculate_liveness,
    ir_pass_optimize_empty_blocks,
    ir_pass_optimize_unused_variables,
    ir_pass_remove_unreachable_blocks,
    ir_pass_dft,
)
from vyper.venom.ir_to_bb_pass import convert_ir_basicblock
from vyper.venom.dfg import calculate_dfg, generate_evm
from vyper.venom.function import IRFunction
from vyper.venom.passes.pass_constant_propagation import ir_pass_constant_propagation


def generate_assembly_experimental(
    ir: IRFunction, optimize: Optional[OptimizationLevel] = None
) -> list[str]:
    return generate_evm(ir, optimize is OptimizationLevel.NONE)


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
        calculate_dfg(ctx)

        changes += ir_pass_constant_propagation(ctx)
        changes += ir_pass_dft(ctx)

        calculate_cfg_in(ctx)
        calculate_liveness(ctx)
        calculate_dfg(ctx)

        if changes == 0:
            break

    return ctx

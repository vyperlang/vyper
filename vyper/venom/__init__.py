# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom.analysis import DFG, calculate_cfg, calculate_liveness
from vyper.venom.bb_optimizer import (
    ir_pass_optimize_empty_blocks,
    ir_pass_optimize_unused_variables,
    ir_pass_remove_unreachable_blocks,
)
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import convert_ir_basicblock
from vyper.venom.passes.constant_propagation import ir_pass_constant_propagation
from vyper.venom.passes.dft import DFTPass
from vyper.venom.venom_to_assembly import VenomCompiler


def generate_assembly_experimental(
    ctx: IRFunction, optimize: Optional[OptimizationLevel] = None
) -> list[str]:
    compiler = VenomCompiler(ctx)
    return compiler.generate_evm(optimize is OptimizationLevel.NONE)


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

        calculate_cfg(ctx)
        calculate_liveness(ctx)

        changes += ir_pass_constant_propagation(ctx)
        changes += DFTPass.run_pass(ctx)

        calculate_cfg(ctx)
        calculate_liveness(ctx)

        if changes == 0:
            break

    return ctx

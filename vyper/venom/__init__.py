# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Any, Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom.analysis import DFG, calculate_cfg, calculate_liveness
from vyper.venom.bb_optimizer import (
    ir_pass_optimize_empty_blocks,
    ir_pass_optimize_unused_variables,
    ir_pass_remove_unreachable_blocks,
)
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.passes.constant_propagation import ir_pass_constant_propagation
from vyper.venom.passes.dft import DFTPass
from vyper.venom.venom_to_assembly import VenomCompiler

DEFAULT_OPT_LEVEL = OptimizationLevel.default()


def generate_assembly_experimental(
    runtime_code: IRFunction,
    deploy_code: Optional[IRFunction] = None,
    optimize: OptimizationLevel = DEFAULT_OPT_LEVEL,
) -> list[str]:
    # note: VenomCompiler is sensitive to the order of these!
    if deploy_code is not None:
        functions = [deploy_code, runtime_code]
    else:
        functions = [runtime_code]

    compiler = VenomCompiler(functions)
    return compiler.generate_evm(optimize == OptimizationLevel.NONE)


def _run_passes(ctx: IRFunction, optimize: OptimizationLevel) -> None:
    # Run passes on Venom IR
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


def generate_ir(ir: IRnode, optimize: OptimizationLevel) -> IRFunction:
    # Convert "old" IR to "new" IR
    ctx = ir_node_to_venom(ir)
    _run_passes(ctx, optimize)

    return ctx

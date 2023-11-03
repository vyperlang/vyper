# REVIEW stylistically i don't really like code (besides just imports)
# going into `__init__.py`. maybe `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom.bb_optimizer import (
    calculate_cfg,
    calculate_liveness,
    ir_pass_optimize_empty_blocks,
    ir_pass_optimize_unused_variables,
    ir_pass_remove_unreachable_blocks,
)
from vyper.venom.function import IRFunction
from vyper.venom.ir_to_assembly import VenomCompiler
from vyper.venom.ir_to_bb_pass import convert_ir_basicblock
from vyper.venom.passes.constant_propagation import ir_pass_constant_propagation
from vyper.venom.passes.dft import DFG, DFTPass


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
        DFG.calculate_dfg(ctx)

        changes += ir_pass_constant_propagation(ctx)
        changes += DFTPass.run_pass(ctx)

        calculate_cfg(ctx)
        calculate_liveness(ctx)
        DFG.calculate_dfg(ctx)

        if changes == 0:
            break

    return ctx

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
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.mem2var import Mem2Var
from vyper.venom.passes.sccp import SCCP
from vyper.venom.passes.simplify_cfg import SimplifyCFGPass
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

    ir_pass_optimize_empty_blocks(ctx)
    ir_pass_remove_unreachable_blocks(ctx)

    internals = [
        bb
        for bb in ctx.basic_blocks
        if bb.label.value.startswith("internal") and len(bb.cfg_in) == 0
    ]

    SimplifyCFGPass().run_pass(ctx, ctx.basic_blocks[0])
    for entry in internals:
        SimplifyCFGPass().run_pass(ctx, entry)

    dfg = DFG.build_dfg(ctx)
    Mem2Var().run_pass(ctx, ctx.basic_blocks[0], dfg)
    for entry in internals:
        Mem2Var().run_pass(ctx, entry, dfg)

    make_ssa_pass = MakeSSA()
    make_ssa_pass.run_pass(ctx, ctx.basic_blocks[0])

    cfg_dirty = False
    sccp_pass = SCCP(make_ssa_pass.dom)
    sccp_pass.run_pass(ctx, ctx.basic_blocks[0])
    cfg_dirty |= sccp_pass.cfg_dirty

    for entry in internals:
        make_ssa_pass.run_pass(ctx, entry)
        sccp_pass = SCCP(make_ssa_pass.dom)
        sccp_pass.run_pass(ctx, entry)
        cfg_dirty |= sccp_pass.cfg_dirty

    calculate_cfg(ctx)
    SimplifyCFGPass().run_pass(ctx, ctx.basic_blocks[0])

    calculate_cfg(ctx)
    calculate_liveness(ctx)

    while True:
        changes = 0

        changes += ir_pass_optimize_empty_blocks(ctx)
        changes += ir_pass_remove_unreachable_blocks(ctx)

        calculate_liveness(ctx)

        changes += ir_pass_optimize_unused_variables(ctx)

        calculate_cfg(ctx)
        calculate_liveness(ctx)

        changes += DFTPass().run_pass(ctx)

        calculate_cfg(ctx)
        calculate_liveness(ctx)

        if changes == 0:
            break


def generate_ir(ir: IRnode, optimize: OptimizationLevel) -> IRFunction:
    # Convert "old" IR to "new" IR
    ctx = ir_node_to_venom(ir)
    _run_passes(ctx, optimize)

    return ctx

# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Dict, List, Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel, Settings, VenomOptimizationFlags
from vyper.ir.compile_ir import AssemblyInstruction
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.fcg import FCGAnalysis
from vyper.venom.basicblock import IRLabel
from vyper.venom.check_venom import check_calling_convention
from vyper.venom.context import DeployInfo, IRContext
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.optimization_levels.O2 import PASSES_O2
from vyper.venom.optimization_levels.O3 import PASSES_O3
from vyper.venom.optimization_levels.Os import PASSES_Os
from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes import (
    CSE,
    SCCP,
    AlgebraicOptimizationPass,
    AssertEliminationPass,
    BranchOptimizationPass,
    DeadStoreElimination,
    FunctionInlinerPass,
    LoadElimination,
    Mem2Var,
    RemoveUnusedVariablesPass,
    SimplifyCFGPass,
)
from vyper.venom.passes.fix_calloca import FixCalloca
from vyper.venom.venom_to_assembly import VenomCompiler

DEFAULT_OPT_LEVEL = OptimizationLevel.default()

# Pass configuration for each optimization level
# TODO: O1 (minimal passes) is currently disabled because it can cause
# "stack too deep" errors. Re-enable once stack spilling machinery is
# implemented to allow compilation with minimal optimization passes.
OPTIMIZATION_PASSES: Dict[OptimizationLevel, List[PassConfig]] = {
    OptimizationLevel.O2: PASSES_O2,
    OptimizationLevel.O3: PASSES_O3,
    OptimizationLevel.Os: PASSES_Os,
}

# Legacy aliases for backwards compatibility
OPTIMIZATION_PASSES[OptimizationLevel.NONE] = OPTIMIZATION_PASSES[
    OptimizationLevel.O2
]  # none -> O2
OPTIMIZATION_PASSES[OptimizationLevel.GAS] = OPTIMIZATION_PASSES[OptimizationLevel.O2]  # gas -> O2
OPTIMIZATION_PASSES[OptimizationLevel.CODESIZE] = OPTIMIZATION_PASSES[
    OptimizationLevel.Os
]  # codesize -> Os


def generate_assembly_experimental(
    venom_ctx: IRContext, optimize: OptimizationLevel = DEFAULT_OPT_LEVEL
) -> list[AssemblyInstruction]:
    compiler = VenomCompiler(venom_ctx)
    return compiler.generate_evm_assembly(optimize == OptimizationLevel.NONE)


# Mapping of pass classes to their disable flag names
# Passes not in this map are considered essential and always run
PASS_FLAG_MAP = {
    AlgebraicOptimizationPass: "disable_algebraic_optimization",
    SCCP: "disable_sccp",
    Mem2Var: "disable_mem2var",
    LoadElimination: "disable_load_elimination",
    RemoveUnusedVariablesPass: "disable_remove_unused_variables",
    DeadStoreElimination: "disable_dead_store_elimination",
    BranchOptimizationPass: "disable_branch_optimization",
    CSE: "disable_cse",
    SimplifyCFGPass: "disable_simplify_cfg",
    AssertEliminationPass: "disable_assert_elimination",
}


def _run_passes(fn: IRFunction, flags: VenomOptimizationFlags, ac: IRAnalysesCache) -> None:
    passes = OPTIMIZATION_PASSES[flags.level]

    for pass_config in passes:
        if isinstance(pass_config, tuple):
            pass_cls, kwargs = pass_config
        else:
            pass_cls = pass_config
            kwargs = {}

        # Check if pass should be skipped based on user flags
        flag_name = PASS_FLAG_MAP.get(pass_cls)

        if flag_name is not None and getattr(flags, flag_name):
            continue

        # Run the pass
        pass_instance = pass_cls(ac, fn)
        pass_instance.run_pass(**kwargs)


def _run_global_passes(
    ctx: IRContext, flags: VenomOptimizationFlags, ir_analyses: dict[IRFunction, IRAnalysesCache]
) -> None:
    FixCalloca(ir_analyses, ctx).run_pass()
    if not flags.disable_inlining:
        FunctionInlinerPass(ir_analyses, ctx, flags).run_pass()


def run_passes_on(ctx: IRContext, flags: VenomOptimizationFlags) -> None:
    ir_analyses: dict[IRFunction, IRAnalysesCache] = {}
    # Validate calling convention invariants before running passes
    check_calling_convention(ctx)
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    _run_global_passes(ctx, flags, ir_analyses)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    assert ctx.entry_function is not None
    fcg = ir_analyses[ctx.entry_function].force_analysis(FCGAnalysis)

    # Remove functions not reachable from entry.
    for fn in fcg.get_unreachable_functions():
        ctx.remove_function(fn)

    _run_fn_passes(ctx, fcg, ctx.entry_function, flags, ir_analyses)


def _run_fn_passes(
    ctx: IRContext,
    fcg: FCGAnalysis,
    fn: IRFunction,
    flags: VenomOptimizationFlags,
    ir_analyses: dict[IRFunction, IRAnalysesCache],
):
    visited: set[IRFunction] = set()
    assert ctx.entry_function is not None
    _run_fn_passes_r(ctx, fcg, ctx.entry_function, flags, ir_analyses, visited)


def _run_fn_passes_r(
    ctx: IRContext,
    fcg: FCGAnalysis,
    fn: IRFunction,
    flags: VenomOptimizationFlags,
    ir_analyses: dict[IRFunction, IRAnalysesCache],
    visited: set,
):
    if fn in visited:
        return
    visited.add(fn)
    for next_fn in fcg.get_callees(fn):
        _run_fn_passes_r(ctx, fcg, next_fn, flags, ir_analyses, visited)

    _run_passes(fn, flags, ir_analyses[fn])


def generate_venom(
    ir: IRnode,
    settings: Settings,
    data_sections: dict[str, bytes] = None,
    deploy_info: Optional[DeployInfo] = None,
) -> IRContext:
    # Convert "old" IR to "new" IR

    ctx = ir_node_to_venom(ir, deploy_info)

    data_sections = data_sections or {}
    for section_name, data in data_sections.items():
        ctx.append_data_section(IRLabel(section_name))
        ctx.append_data_item(data)

    flags = settings.get_venom_flags()
    run_passes_on(ctx, flags)

    return ctx

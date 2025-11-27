# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Any, Dict, List

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel, Settings, VenomOptimizationFlags
from vyper.ir.compile_ir import AssemblyInstruction
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel, IRLiteral
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.optimization_levels import PASSES_O2, PASSES_O3, PASSES_Os
from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes import (
    CSE,
    SCCP,
    AlgebraicOptimizationPass,
    AssignElimination,
    BranchOptimizationPass,
    CFGNormalization,
    DeadStoreElimination,
    DFTPass,
    FloatAllocas,
    FunctionInlinerPass,
    LoadElimination,
    LowerDloadPass,
    MakeSSA,
    Mem2Var,
    MemMergePass,
    PhiEliminationPass,
    ReduceLiteralsCodesize,
    RemoveUnusedVariablesPass,
    RevertToAssert,
    SimplifyCFGPass,
    SingleUseExpansion,
)
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
    return compiler.generate_evm_assembly(False)


# Mapping of pass names to their disable flag names
# Passes not in this map are considered essential and always run
PASS_FLAG_MAP = {
    "AlgebraicOptimizationPass": "disable_algebraic_optimization",
    "SCCP": "disable_sccp",
    "Mem2Var": "disable_mem2var",
    "LoadElimination": "disable_load_elimination",
    "RemoveUnusedVariablesPass": "disable_remove_unused_variables",
    "DeadStoreElimination": "disable_dead_store_elimination",
    "BranchOptimizationPass": "disable_branch_optimization",
    "CSE": "disable_cse",
    "SimplifyCFGPass": "disable_simplify_cfg",
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
        pass_name = pass_cls.__name__
        flag_name = PASS_FLAG_MAP.get(pass_name)

        if flag_name and getattr(flags, flag_name):
            continue

        # Run the pass
        pass_instance = pass_cls(ac, fn)
        pass_instance.run_pass(**kwargs)


def _run_global_passes(
    ctx: IRContext, flags: VenomOptimizationFlags, ir_analyses: dict[IRFunction, IRAnalysesCache]
) -> None:
    if not flags.disable_inlining:
        FunctionInlinerPass(ir_analyses, ctx, flags).run_pass()


def run_passes_on(ctx: IRContext, flags: VenomOptimizationFlags) -> None:
    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    _run_global_passes(ctx, flags, ir_analyses)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    for fn in ctx.functions.values():
        _run_passes(fn, flags, ir_analyses[fn])


def generate_venom(
    ir: IRnode,
    settings: Settings,
    constants: dict[str, int] = None,
    data_sections: dict[str, bytes] = None,
) -> IRContext:
    # Convert "old" IR to "new" IR
    constants = constants or {}
    starting_symbols = {k: IRLiteral(v) for k, v in constants.items()}
    ctx = ir_node_to_venom(ir, starting_symbols)

    data_sections = data_sections or {}
    for section_name, data in data_sections.items():
        ctx.append_data_section(IRLabel(section_name))
        ctx.append_data_item(data)

    for constname, value in constants.items():
        ctx.add_constant(constname, value)

    assert settings.venom_flags is not None
    run_passes_on(ctx, settings.venom_flags)

    return ctx

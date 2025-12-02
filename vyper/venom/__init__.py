from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT
from vyper.ir.compile_ir import AssemblyInstruction
from vyper.venom.analysis import FCGAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRAbstractMemLoc, IRLabel, IRLiteral
from vyper.venom.check_venom import check_calling_convention
from vyper.venom.context import DeployInfo, IRContext
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.memory_location import fix_mem_loc
from vyper.venom.passes import (
    CSE,
    SCCP,
    AlgebraicOptimizationPass,
    AssignElimination,
    BranchOptimizationPass,
    CFGNormalization,
    ConcretizeMemLocPass,
    DFTPass,
    FixCalloca,
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
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.venom_to_assembly import VenomCompiler

DEFAULT_OPT_LEVEL = OptimizationLevel.default()


def generate_assembly_experimental(
    venom_ctx: IRContext, optimize: OptimizationLevel = DEFAULT_OPT_LEVEL
) -> list[AssemblyInstruction]:
    compiler = VenomCompiler(venom_ctx)
    return compiler.generate_evm_assembly(optimize == OptimizationLevel.NONE)


def _run_passes(fn: IRFunction, optimize: OptimizationLevel, ac: IRAnalysesCache) -> None:
    # Run passes on Venom IR
    # TODO: Add support for optimization levels

    FloatAllocas(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()

    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()

    # run constant folding before mem2var to reduce some pointer arithmetic
    AlgebraicOptimizationPass(ac, fn).run_pass()
    SCCP(ac, fn, remove_allocas=False).run_pass()
    SimplifyCFGPass(ac, fn).run_pass()

    AssignElimination(ac, fn).run_pass()
    Mem2Var(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()
    SCCP(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()
    AssignElimination(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()

    LoadElimination(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()
    AssignElimination(ac, fn).run_pass()

    SCCP(ac, fn).run_pass()
    AssignElimination(ac, fn).run_pass()
    RevertToAssert(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    DeadStoreElimination(ac, fn).run_pass(addr_space=MEMORY)
    DeadStoreElimination(ac, fn).run_pass(addr_space=STORAGE)
    DeadStoreElimination(ac, fn).run_pass(addr_space=TRANSIENT)

    AssignElimination(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()
    ConcretizeMemLocPass(ac, fn).run_pass()
    SCCP(ac, fn).run_pass()
    SimplifyCFGPass(ac, fn).run_pass()

    # run memmerge before LowerDload
    MemMergePass(ac, fn).run_pass()
    LowerDloadPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()
    BranchOptimizationPass(ac, fn).run_pass()

    AlgebraicOptimizationPass(ac, fn).run_pass()

    # This improves the performance of cse
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    PhiEliminationPass(ac, fn).run_pass()
    AssignElimination(ac, fn).run_pass()
    CSE(ac, fn).run_pass()

    AssignElimination(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()
    SingleUseExpansion(ac, fn).run_pass()

    if optimize == OptimizationLevel.CODESIZE:
        ReduceLiteralsCodesize(ac, fn).run_pass()

    DFTPass(ac, fn).run_pass()

    CFGNormalization(ac, fn).run_pass()


def _run_global_passes(ctx: IRContext, optimize: OptimizationLevel, ir_analyses: dict) -> None:
    FixCalloca(ir_analyses, ctx).run_pass()
    FunctionInlinerPass(ir_analyses, ctx, optimize).run_pass()


def run_passes_on(ctx: IRContext, optimize: OptimizationLevel) -> None:
    ir_analyses = {}
    # Validate calling convention invariants before running passes
    check_calling_convention(ctx)
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    _run_global_passes(ctx, optimize, ir_analyses)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    assert ctx.entry_function is not None
    fcg = ir_analyses[ctx.entry_function].force_analysis(FCGAnalysis)

    _run_fn_passes(ctx, fcg, ctx.entry_function, optimize, ir_analyses)


def _run_fn_passes(
    ctx: IRContext, fcg: FCGAnalysis, fn: IRFunction, optimize: OptimizationLevel, ir_analyses: dict
):
    visited: set[IRFunction] = set()
    assert ctx.entry_function is not None
    _run_fn_passes_r(ctx, fcg, ctx.entry_function, optimize, ir_analyses, visited)


def _run_fn_passes_r(
    ctx: IRContext,
    fcg: FCGAnalysis,
    fn: IRFunction,
    optimize: OptimizationLevel,
    ir_analyses: dict,
    visited: set,
):
    if fn in visited:
        return
    visited.add(fn)
    for next_fn in fcg.get_callees(fn):
        _run_fn_passes_r(ctx, fcg, next_fn, optimize, ir_analyses, visited)

    _run_passes(fn, optimize, ir_analyses[fn])


def generate_venom(
    ir: IRnode,
    settings: Settings,
    constants: Optional[dict[str, int]] = None,
    deploy: Optional[DeployInfo] = None,
) -> IRContext:
    constants = constants or {}
    data_sections = {}
    if deploy is not None:
        data_sections = deploy.data_sections

    starting_symbols = {k: IRLiteral(v) for k, v in constants.items()}

    def _build_ctx(ctor_override: int | None) -> IRContext:
        ctx = ir_node_to_venom(ir, starting_symbols, ctor_mem_override=ctor_override, deploy=deploy)

        ctx.mem_allocator.allocate(IRAbstractMemLoc.FREE_VAR1)
        ctx.mem_allocator.allocate(IRAbstractMemLoc.FREE_VAR2)

        # Pre-seed deploy_mem at offset 0 because codecopy/iload/istore
        # use runtime_code_start for absolute offsets. Restore eom so ctor scratch
        # allocations start from the normal baseline
        # (deploy_mem shouldn't bump the ctor watermark).
        if ctx.deploy_mem is not None:
            old_eom = ctx.mem_allocator.eom
            ctx.mem_allocator.allocate_fixed_at(ctx.deploy_mem, 0)
            ctx.mem_allocator.eom = old_eom

        for fn in ctx.functions.values():
            fix_mem_loc(fn)

        for section_name, data in data_sections.items():
            ctx.append_data_section(IRLabel(section_name))
            ctx.append_data_item(data)

        for constname, value in constants.items():
            ctx.add_constant(constname, value)

        optimize = settings.optimize
        assert optimize is not None  # help mypy
        run_passes_on(ctx, optimize)
        return ctx

    # For deploy contexts, do a two-pass build: first to measure peak venom ctor
    # memory (excluding the deploy region), then rebuild with that watermark.
    if deploy is not None:
        first_ctx = _build_ctx(None)
        peak = 0
        skip_ids = {IRAbstractMemLoc.FREE_VAR1._id, IRAbstractMemLoc.FREE_VAR2._id}
        if first_ctx.deploy_mem is not None:
            skip_ids.add(first_ctx.deploy_mem._id)
        for mem_id, (ptr, size) in first_ctx.mem_allocator.allocated.items():
            if mem_id in skip_ids:
                continue
            peak = max(peak, ptr + size)

        final_ctx = _build_ctx(peak)

        # sanity: ensure final peak does not exceed initial peak
        final_peak = 0
        if final_ctx.deploy_mem is not None:
            skip_ids.add(final_ctx.deploy_mem._id)
        for mem_id, (ptr, size) in final_ctx.mem_allocator.allocated.items():
            if mem_id in skip_ids:
                continue
            final_peak = max(final_peak, ptr + size)
        assert (
            final_peak <= peak
        ), f"ctor peak grew after override: initial {peak}, final {final_peak}"

        return final_ctx

    return _build_ctx(None)

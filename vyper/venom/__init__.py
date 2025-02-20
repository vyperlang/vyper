# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.passes import (
    SCCP,
    AlgebraicOptimizationPass,
    BranchOptimizationPass,
    DFTPass,
    FloatAllocas,
    FunctionInlinerPass,
    LoadElimination,
    LowerDloadPass,
    MakeSSA,
    Mem2Var,
    MemMergePass,
    ReduceLiteralsCodesize,
    RemoveUnusedVariablesPass,
    SimplifyCFGPass,
    StoreElimination,
    StoreExpansionPass,
)
from vyper.venom.venom_to_assembly import VenomCompiler

DEFAULT_OPT_LEVEL = OptimizationLevel.default()


def generate_assembly_experimental(
    runtime_code: IRContext,
    deploy_code: Optional[IRContext] = None,
    optimize: OptimizationLevel = DEFAULT_OPT_LEVEL,
) -> list[str]:
    # note: VenomCompiler is sensitive to the order of these!
    if deploy_code is not None:
        functions = [deploy_code, runtime_code]
    else:
        functions = [runtime_code]

    compiler = VenomCompiler(functions)
    return compiler.generate_evm(optimize == OptimizationLevel.NONE)


def _run_passes(fn: IRFunction, optimize: OptimizationLevel, ac: IRAnalysesCache) -> None:
    # Run passes on Venom IR
    # TODO: Add support for optimization levels

    FloatAllocas(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()
    # run algebraic opts before mem2var to reduce some pointer arithmetic
    AlgebraicOptimizationPass(ac, fn).run_pass()
    StoreElimination(ac, fn).run_pass()
    Mem2Var(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()
    SCCP(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()
    StoreElimination(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()
    LoadElimination(ac, fn).run_pass()
    SCCP(ac, fn).run_pass()
    StoreElimination(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    LowerDloadPass(ac, fn).run_pass()
    # NOTE: MakeSSA is after algebraic optimization it currently produces
    #       smaller code by adding some redundant phi nodes. This is not a
    #       problem for us, but we need to be aware of it, and should be
    #       removed when the dft pass is fixed to produce the smallest code
    #       without making the code generation more expensive by running
    #       MakeSSA again.
    MakeSSA(ac, fn).run_pass()
    BranchOptimizationPass(ac, fn).run_pass()

    AlgebraicOptimizationPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    StoreExpansionPass(ac, fn).run_pass()

    if optimize == OptimizationLevel.CODESIZE:
        ReduceLiteralsCodesize(ac, fn).run_pass()

    DFTPass(ac, fn).run_pass()


def _run_global_passes(ctx: IRContext, optimize: OptimizationLevel, ir_analyses: dict) -> None:
    FunctionInlinerPass(ir_analyses, ctx, optimize).run_pass()


def run_passes_on(ctx: IRContext, optimize: OptimizationLevel) -> None:
    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    _run_global_passes(ctx, optimize, ir_analyses)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    for fn in ctx.functions.values():
        _run_passes(fn, optimize, ir_analyses[fn])


def generate_ir(ir: IRnode, settings: Settings) -> IRContext:
    # Convert "old" IR to "new" IR
    ctx = ir_node_to_venom(ir)

    optimize = settings.optimize
    assert optimize is not None  # help mypy
    run_passes_on(ctx, optimize)

    return ctx

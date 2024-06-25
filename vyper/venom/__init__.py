# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ir_node_to_venom
from vyper.venom.passes.algebraic_optimization import AlgebraicOptimizationPass
from vyper.venom.passes.branch_optimization import BranchOptimizationPass
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.extract_literals import ExtractLiteralsPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.mem2var import Mem2Var
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass
from vyper.venom.passes.sccp import SCCP
from vyper.venom.passes.simplify_cfg import SimplifyCFGPass
from vyper.venom.passes.store_elimination import StoreElimination
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


def _run_passes(fn: IRFunction, optimize: OptimizationLevel) -> None:
    # Run passes on Venom IR
    # TODO: Add support for optimization levels

    ac = IRAnalysesCache(fn)

    SimplifyCFGPass(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()
    Mem2Var(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()
    SCCP(ac, fn).run_pass()
    StoreElimination(ac, fn).run_pass()
    SimplifyCFGPass(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()
    BranchOptimizationPass(ac, fn).run_pass()
    ExtractLiteralsPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()
    DFTPass(ac, fn).run_pass()


def generate_ir(ir: IRnode, optimize: OptimizationLevel) -> IRContext:
    # Convert "old" IR to "new" IR
    ctx = ir_node_to_venom(ir)
    for fn in ctx.functions.values():
        _run_passes(fn, optimize)

    return ctx

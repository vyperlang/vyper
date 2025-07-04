# maybe rename this `main.py` or `venom.py`
# (can have an `__init__.py` which exposes the API).

from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT
from vyper.evm.assembler.core import AssemblyInstruction
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import MemSSA
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRHexString, IRLabel, IRLiteral, IROperand
from vyper.venom.const_eval import try_evaluate_const_expr
from vyper.venom.context import DataSection, IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes import (
    CSE,
    SCCP,
    AlgebraicOptimizationPass,
    AssignElimination,
    BranchOptimizationPass,
    CFGNormalization,
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

    SCCP(ac, fn).run_pass()
    AssignElimination(ac, fn).run_pass()
    RevertToAssert(ac, fn).run_pass()

    SimplifyCFGPass(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    DeadStoreElimination(ac, fn).run_pass(addr_space=MEMORY)
    DeadStoreElimination(ac, fn).run_pass(addr_space=STORAGE)
    DeadStoreElimination(ac, fn).run_pass(addr_space=TRANSIENT)
    LowerDloadPass(ac, fn).run_pass()

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


def _resolve_const_operands(ctx: IRContext) -> None:
    """Resolve raw const expressions in operands to IRLiteral or IRLabel."""
    for fn in ctx.functions.values():
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                new_operands = []
                for op in inst.operands:
                    if isinstance(op, (str, tuple)) and not isinstance(op, IROperand):
                        # This is a raw const expression - evaluate it
                        result = try_evaluate_const_expr(
                            op, ctx.constants, ctx.global_labels,
                            ctx.unresolved_consts, ctx.const_refs
                        )
                        if isinstance(result, int):
                            new_operands.append(IRLiteral(result))
                        else:
                            # Return as label for unresolved expressions
                            new_operands.append(IRLabel(result, True))
                    else:
                        new_operands.append(op)
                inst.operands = new_operands


def _run_global_passes(ctx: IRContext, optimize: OptimizationLevel, ir_analyses: dict) -> None:
    FunctionInlinerPass(ir_analyses, ctx, optimize).run_pass()


def run_passes_on(ctx: IRContext, optimize: OptimizationLevel) -> None:
    # First resolve any raw const expressions in operands
    _resolve_const_operands(ctx)
    
    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    _run_global_passes(ctx, optimize, ir_analyses)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    for fn in ctx.functions.values():
        _run_passes(fn, optimize, ir_analyses[fn])

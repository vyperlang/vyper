import glob
from pathlib import Path

import pytest

from vyper.venom.passes import (
    AffineFoldingPass,
    AlgebraicOptimizationPass,
    AssertCombinerPass,
    AssertEliminationPass,
    AssignElimination,
    BranchOptimizationPass,
    CSE,
    DeadStoreElimination,
    DFTPass,
    FunctionInlinerPass,
    InternalReturnCopyForwardingPass,
    ReduceLiteralsCodesize,
    LoadElimination,
    Mem2Var,
    MemMergePass,
    MemoryCopyElisionPass,
    OverflowEliminationPass,
    PhiEliminationPass,
    ReadonlyInvokeArgCopyForwardingPass,
    RemoveUnusedVariablesPass,
    RevertToAssert,
    SCCP,
    TailMergePass,
)

from vyper.venom import OPTIMIZATION_PASSES

import vyper.compiler as compiler

dir_path = Path(__file__).parent


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir=dir_path, recursive=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_compile(vy_filename):
    with open(dir_path / vy_filename) as f:
        source_code = f.read()
    compiler.compile_code(source_code)

@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
@pytest.mark.parametrize("pass_to_disable", [
    AffineFoldingPass,
    AlgebraicOptimizationPass,
    AssertCombinerPass,
    AssertEliminationPass,
    AssignElimination,
    BranchOptimizationPass,
    CSE,
    DeadStoreElimination,
    DFTPass,
    FunctionInlinerPass,
    InternalReturnCopyForwardingPass,
    ReduceLiteralsCodesize,
    LoadElimination,
    Mem2Var,
    MemMergePass,
    MemoryCopyElisionPass,
    OverflowEliminationPass,
    PhiEliminationPass,
    ReadonlyInvokeArgCopyForwardingPass,
    RemoveUnusedVariablesPass,
    RevertToAssert,
    SCCP,
    TailMergePass,
])
def test_compile_pass_fuzz(vy_filename, pass_to_disable, compiler_settings, monkeypatch):
    if not compiler_settings.experimental_codegen:
        pytest.skip()

    if pass_to_disable not in OPTIMIZATION_PASSES[compiler_settings.optimize] and pass_to_disable != FunctionInlinerPass:
        pytest.skip()

    with open(dir_path / vy_filename) as f:
        source_code = f.read()
    
    run = []
    def temp(*args, **kwargs):
        run.append(True)

    monkeypatch.setattr(pass_to_disable, "run_pass", temp)

    compiler.compile_code(source_code)

    assert len(run) != 0 and all(run)

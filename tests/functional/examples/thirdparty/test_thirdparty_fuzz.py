import glob
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

import vyper.compiler as compiler
from vyper.venom.passes import (
    CSE,
    SCCP,
    AffineFoldingPass,
    AlgebraicOptimizationPass,
    AssertCombinerPass,
    AssertEliminationPass,
    AssignElimination,
    BranchOptimizationPass,
    DeadStoreElimination,
    DFTPass,
    InternalReturnCopyForwardingPass,
    LoadElimination,
    Mem2Var,
    MemMergePass,
    MemoryCopyElisionPass,
    OverflowEliminationPass,
    PhiEliminationPass,
    ReadonlyInvokeArgCopyForwardingPass,
    ReduceLiteralsCodesize,
    RevertToAssert,
    TailMergePass,
)

dir_path = Path(__file__).parent


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir=dir_path, recursive=True)


pass_to_disable = [
    AffineFoldingPass,
    AlgebraicOptimizationPass,
    AssertCombinerPass,
    AssertEliminationPass,
    AssignElimination,
    BranchOptimizationPass,
    CSE,
    DeadStoreElimination,
    DFTPass,
    InternalReturnCopyForwardingPass,
    ReduceLiteralsCodesize,
    LoadElimination,
    Mem2Var,
    MemMergePass,
    MemoryCopyElisionPass,
    OverflowEliminationPass,
    PhiEliminationPass,
    ReadonlyInvokeArgCopyForwardingPass,
    RevertToAssert,
    SCCP,
    TailMergePass,
]

any_passes = st.lists(st.sampled_from(pass_to_disable), min_size=2, max_size=10, unique=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
@settings(
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=10,
    phases=[Phase.generate],
)
@given(passes_to_disable=any_passes)
@pytest.mark.fuzzing
def test_compile_pass_fuzz(vy_filename, passes_to_disable, compiler_settings, monkeypatch):
    if not compiler_settings.experimental_codegen:
        pytest.skip()

    with open(dir_path / vy_filename) as f:
        source_code = f.read()

    run = []

    def temp(*args, **kwargs):
        run.append(True)

    for pass_to_disable in passes_to_disable:
        monkeypatch.setattr(pass_to_disable, "run_pass", temp)

    compiler.compile_code(source_code)

    assert len(run) != 0 and all(run)

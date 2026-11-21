import glob
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

import vyper.compiler as compiler
from vyper.venom.optimization_levels.O1 import PASSES_O1
from vyper.venom.optimization_levels.O2 import PASSES_O2
from vyper.venom.optimization_levels.O3 import PASSES_O3
from vyper.venom.optimization_levels.Os import PASSES_Os
from vyper.venom.passes import (
    CFGNormalization,
    ConcretizeMemLocPass,
    FmpLoweringPass,
    LowerDloadPass,
    MakeSSA,
    SimplifyCFGPass,
    SingleUseExpansion,
)

dir_path = Path(__file__).parent


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir=dir_path, recursive=True)


O1_types = {x[0] if isinstance(x, tuple) else x for x in PASSES_O1}
O2_types = {x[0] if isinstance(x, tuple) else x for x in PASSES_O2}
O3_types = {x[0] if isinstance(x, tuple) else x for x in PASSES_O3}
Os_types = {x[0] if isinstance(x, tuple) else x for x in PASSES_Os}

pass_to_disable = list(
    O1_types.union(O2_types)
    .union(O3_types)
    .union(Os_types)
    .difference(
        (
            MakeSSA,
            ConcretizeMemLocPass,
            LowerDloadPass,
            SimplifyCFGPass,
            SingleUseExpansion,
            CFGNormalization,
            FmpLoweringPass,
        )
    )
)

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

    with monkeypatch.context() as m:
        run = []

        def temp(*args, **kwargs):
            run.append(True)

        for pass_to_disable in passes_to_disable:
            m.setattr(pass_to_disable, "run_pass", temp)

        compiler.compile_code(source_code)

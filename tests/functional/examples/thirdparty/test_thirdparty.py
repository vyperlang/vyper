import glob
from pathlib import Path

import pytest

import vyper.compiler as compiler
from vyper.compiler.settings import OptimizationLevel

dir_path = Path(__file__).parent


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir=dir_path, recursive=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_compile(vy_filename, compiler_settings, request):
    if (
        vy_filename == "curvefi/CurveStableSwapMetaNG.vy"
        and compiler_settings.experimental_codegen
        and compiler_settings.optimize == OptimizationLevel.NONE
    ):
        # fails with StackTooDeep
        request.node.add_marker(pytest.mark.xfail(strict=True))

    with open(dir_path / vy_filename) as f:
        source_code = f.read()
    compiler.compile_code(source_code)

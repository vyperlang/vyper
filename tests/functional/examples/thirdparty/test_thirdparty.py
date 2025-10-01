import glob
from pathlib import Path

import pytest

import vyper.compiler as compiler

dir_path = Path(__file__).parent


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir=dir_path, recursive=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_compile(vy_filename):
    if vy_filename == "curvefi/amm/stableswap/implementation/implementation_v_700.vy":
        pytest.xfail("StackTooDeep: Unsupported dup depth 17")

    with open(dir_path / vy_filename) as f:
        source_code = f.read()
    compiler.compile_code(source_code)

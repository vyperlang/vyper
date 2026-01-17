import glob
import warnings
from pathlib import Path

import pytest

import vyper.compiler as compiler
import vyper.warnings

dir_path = Path(__file__).parent


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir=dir_path, recursive=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_compile(vy_filename):
    if vy_filename == "curvefi/amm/stableswap/implementation/implementation_v_700.vy":
        pytest.xfail("StackTooDeep: Unsupported dup depth 17")

    with open(dir_path / vy_filename) as f:
        source_code = f.read()

    with warnings.catch_warnings():
        # These examples predate ... being allowed in interfaces
        warnings.filterwarnings(
            "ignore",
            message=r"Please use `\.\.\.` as default value\.",
            category=vyper.warnings.Deprecation,
        )
        compiler.compile_code(source_code)

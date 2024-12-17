import glob

import pytest

from tests.venom_utils import assert_ctx_eq, parse_venom
from vyper.compiler import compile_code
from vyper.venom.context import IRContext

"""
Check that venom text format round-trips through parser
"""


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir="examples/", recursive=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_round_trip(vy_filename):
    path = f"examples/{vy_filename}"
    with open(path) as f:
        vyper_source = f.read()

    out = compile_code(vyper_source, output_formats=["bb_runtime"])
    bb_runtime = out["bb_runtime"]
    venom_code = IRContext.__repr__(bb_runtime)

    ctx = parse_venom(venom_code)

    assert_ctx_eq(bb_runtime, ctx)

import pytest
import glob
from pathlib import Path
import vyper.compiler as compiler
import os


dir_path = Path(__file__).parent

def get_example_vy_filenames():

    return glob.glob("**/*.vy", root_dir = dir_path, recursive=True)

@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_compile(vy_filename):
    with open(dir_path / vy_filename) as f:
        source_code = f.read()
    compiler.compile_code(source_code)

import os

import pytest

from vyper.cli.vyper_compile import _parse_args


@pytest.fixture
def chdir_path(tmp_path):
    orig_path = os.getcwd()
    yield tmp_path
    os.chdir(orig_path)


def test_paths(chdir_path):
    code = """
@external
def foo() -> bool:
    return True
"""
    bar_path = chdir_path.joinpath("bar.vy")
    with bar_path.open("w") as fp:
        fp.write(code)

    _parse_args([str(bar_path)])  # absolute path
    os.chdir(chdir_path.parent)

    _parse_args([str(bar_path)])  # absolute path, subfolder of cwd
    _parse_args([str(bar_path.relative_to(chdir_path.parent))])  # relative path

import os
from vyper.warnings import VyperWarning
import warnings

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

def test_warnings(make_file):
    """
    test -Werror and -Wnone
    """
    # test code which emits warnings
    code = """
@external
def foo():
    breakpoint()
    """
    path = make_file("foo.vy", code)
    path_str = str(path)

    # (1)
    # test promote warnings to error
    # doesn't work if it runs after (2)!
    with pytest.raises(VyperWarning) as e:
        _parse_args([path_str, "-Werror"])

    # (2)
    with warnings.catch_warnings(record=True) as w:
        _parse_args([str(path)])

    assert len(w) == 1
    warning_message = w[0].message.message

    assert e.value.message == warning_message

    # test squashing warnings
    with warnings.catch_warnings(record=True) as w:
        _parse_args([path_str, "-Wnone"])
    assert len(w) == 0

    warnings.resetwarnings()

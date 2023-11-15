import pytest

from vyper import compiler

valid_list = [
    """
FOO: constant(int256) = -3
BAR: constant(int256) = abs(FOO)
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_addmulmod_pass(code):
    assert compiler.compile_code(code) is not None
import pytest

from vyper import compiler

valid_list = [
    """
FOO: constant(uint256) = 3
BAR: constant(uint256) = 5
BAZ: constant(uint256) = pow_mod256(FOO, BAR)
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_addmulmod_pass(code):
    assert compiler.compile_code(code) is not None

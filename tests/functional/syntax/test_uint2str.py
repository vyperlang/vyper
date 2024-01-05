import pytest

from vyper import compile_code

valid_list = [
    """
FOO: constant(uint256) = 3
BAR: constant(String[78]) = uint2str(FOO)

@external
def foo():
    a: String[78] = BAR
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_addmulmod_pass(code):
    assert compile_code(code) is not None

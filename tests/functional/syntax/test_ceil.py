import pytest

from vyper import compile_code

valid_list = [
    """
BAR: constant(decimal) = 2.5
FOO: constant(int256) = ceil(BAR)

@external
def foo():
    a: int256 = FOO
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_ceil_good(code):
    assert compile_code(code) is not None

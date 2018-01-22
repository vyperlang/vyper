import pytest

from viper import compiler

valid_list = [
    """
@public
def foo():
    for i in range(10):
        pass
    """,
    """
@public
def foo():
    for i in range(10, 20):
        pass
    """,
    """
@public
def foo():
    x: num = 5
    for i in range(x, x + 10):
        pass
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_range_success(good_code):
    assert compiler.compile(good_code) is not None

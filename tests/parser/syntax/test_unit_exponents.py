import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException

fail_list = [
    """
@public
def baa() -> decimal:
    return 2.0 ** 2
    """,
    """
@public
def foo(a:num):
    b:num(sec)
    c:num(sec**2)
    c = b ** a
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_exponent_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo():
    a : num(wei)
    b : num(wei**2)
    a = 2
    b = a**2
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_exponent_success(good_code):
    assert compiler.compile(good_code) is not None

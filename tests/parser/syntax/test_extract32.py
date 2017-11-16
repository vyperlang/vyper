import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException

fail_list = [
    """
@public
def foo() -> num256:
    return extract32("cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_extract32_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo() -> num256:
    return extract32("cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0, type=num256)
    """,
    """
x: bytes <= 100
@public
def foo() -> num256:
    self.x = "cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 0, type=num256)
    """,
    """
x: bytes <= 100
@public
def foo() -> num256:
    self.x = "cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 1, type=num256)
"""
]


@pytest.mark.parametrize('good_code', valid_list)
def test_extract32_success(good_code):
    assert compiler.compile(good_code) is not None

import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import NonPayableViolationException


fail_list = [
    """
@public
def foo():
    x = msg.value
"""
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_decleration_exception(bad_code):
        with raises(NonPayableViolationException):
            compiler.compile(bad_code)


valid_list = [
    """
x: num
@public
@payable
def foo() -> num:
    self.x = 5
    return self.x
    """,
    """
@public
@payable
def foo():
    x: wei_value = msg.value
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None

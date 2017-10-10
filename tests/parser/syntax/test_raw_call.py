import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    ("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, outsize=9)
    """, SyntaxError),
    """
def foo():
    raw_log(["cow"], "dog")
    """,
    """
def foo():
    raw_log([], 0x1234567890123456789012345678901234567890)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_raw_call_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757)
    """,
    """
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757, value=as_wei_value(9, wei))
    """,
    """
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757, value=9)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_raw_call_success(good_code):
    assert compiler.compile(good_code) is not None

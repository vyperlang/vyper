import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def foo():
    x = true
    x = 5
    """,
    ("""
def foo():
    True = 3
    """, SyntaxError),
    """
def foo():
    x = True
    x = 129
    """,
    """
def foo() -> bool:
    return (1 == 2) <= (1 == 1)
    """,
    """
def foo() -> bool:
    return (1 == 2) or 3
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_bool_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
def foo():
    x = true
    z = x and false
    """,
    """
def foo():
    x = true
    z = x and False
    """,
    """
def foo():
    x = True
    x = False
    """,
    """
def foo() -> bool:
    return 1 == 1
    """,
    """
def foo() -> bool:
    return 1 != 1
    """,
    """
def foo() -> bool:
    return 1 > 1
    """,
    """
def foo() -> bool:
    return 1. >= 1
    """,
    """
def foo() -> bool:
    return 1 < 1
    """,
    """
def foo() -> bool:
    return 1 <= 1.
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_bool_success(good_code):
    assert compiler.compile(good_code) is not None

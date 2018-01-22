import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def foo():
    x: bool = true
    x = 5
    """,
    ("""
@public
def foo():
    True = 3
    """, SyntaxError),
    """
@public
def foo():
    x: bool = True
    x = 129
    """,
    """
@public
def foo() -> bool:
    return (1 == 2) <= (1 == 1)
    """,
    """
@public
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
@public
def foo():
    x: bool = true
    z: bool = x and false
    """,
    """
@public
def foo():
    x: bool = true
    z: bool = x and False
    """,
    """
@public
def foo():
    x: bool = True
    x = False
    """,
    """
@public
def foo() -> bool:
    return 1 == 1
    """,
    """
@public
def foo() -> bool:
    return 1 != 1
    """,
    """
@public
def foo() -> bool:
    return 1 > 1
    """,
    """
@public
def foo() -> bool:
    return 1. >= 1
    """,
    """
@public
def foo() -> bool:
    return 1 < 1
    """,
    """
@public
def foo() -> bool:
    return 1 <= 1.
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_bool_success(good_code):
    assert compiler.compile(good_code) is not None

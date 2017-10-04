import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def baa():
    x: bytes <= 50
    y: bytes <= 50
    z = x + y
    """,
    """
def baa():
    x: bytes <= 50
    y: num
    y = x
    """,
    """
def baa():
    x: bytes <= 50
    y: num
    x = y
    """,
    """
def baa():
    x: bytes <= 50
    y: bytes <= 60
    x = y
    """,
    """
def foo(x: bytes <= 100) -> bytes <= 75:
    return x
    """,
    """
def foo(x: bytes <= 100) -> num:
    return x
    """,
    """
def foo(x: num) -> bytes <= 75:
    return x
    """,
    """
def convert2(inp: num256) -> address:
    return as_bytes32(inp)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_bytes_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
def foo(x: bytes <= 100) -> bytes <= 100:
    return x
    """,
    """
def foo(x: bytes <= 100) -> bytes <= 150:
    return x
    """,

    """
def convert2(inp: num256) -> bytes32:
    return as_bytes32(inp)
    """,
    """
def baa():
    x: bytes <= 50
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_bytes_success(good_code):
    assert compiler.compile(good_code) is not None

import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def baa():
    x: bytes <= 50
    y: bytes <= 50
    z = x + y
    """,
    """
@public
def baa():
    x: bytes <= 50
    y: num
    y = x
    """,
    """
@public
def baa():
    x: bytes <= 50
    y: num
    x = y
    """,
    """
@public
def baa():
    x: bytes <= 50
    y: bytes <= 60
    x = y
    """,
    """
@public
def foo(x: bytes <= 100) -> bytes <= 75:
    return x
    """,
    """
@public
def foo(x: bytes <= 100) -> num:
    return x
    """,
    """
@public
def foo(x: num) -> bytes <= 75:
    return x
    """,
    """
@public
def foo() -> bytes <= 10:
    x: bytes <= 10 = '0x1234567890123456789012345678901234567890'
    x = 0x1234567890123456789012345678901234567890
    """,
    """
@public
def foo() -> bytes <= 10:
    return "badmintonzz"
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_bytes_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo(x: bytes <= 100) -> bytes <= 100:
    return x
    """,
    """
@public
def foo(x: bytes <= 100) -> bytes <= 150:
    return x
    """,
    """
@public
def convert2(inp: num256) -> bytes32:
    return as_bytes32(inp)
    """,
    """
@public
def baa():
    x: bytes <= 50
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_bytes_success(good_code):
    assert compiler.compile(good_code) is not None

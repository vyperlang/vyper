import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def foo(inp: bytes <= 10) -> bytes <= 2:
    return slice(inp, start=2, len=3)
    """,
    """
@public
def foo(inp: num) -> bytes <= 3:
    return slice(inp, start=2, len=3)
    """,
    """
@public
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=4.0, len=3)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_slice_fail(bad_code):

    with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
@public
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=2, len=3)
    """,
    """
@public
def foo(inp: bytes <= 10) -> bytes <= 4:
    return slice(inp, start=2, len=3)
    """,
    """
@public
def foo() -> bytes <= 10:
    return slice("badmintonzzz", start=1, len=10)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_slice_success(good_code):
    assert compiler.compile(good_code) is not None

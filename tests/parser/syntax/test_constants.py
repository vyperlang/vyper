import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException


fail_list = [
    """
VAL: constant(uint256) = -123
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
VAL: constant(uint256) = 123
    """,
    """
VAL: constant(int128) = -123
@public
def test() -> int128:
    return 1 * VAL
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_as_wei_success(good_code):
    assert compiler.compile(good_code) is not None

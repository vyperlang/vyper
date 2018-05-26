import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def foo():
    x: int128(wei) = as_wei_value(5, szabo)
    """,
    """
@public
def foo() -> int128(wei):
    x: int128(wei) = 45
    return x.balance
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):
    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo():
    x: uint256(wei) = as_wei_value(5, "finney") + as_wei_value(2, "babbage") + as_wei_value(8, "shannon")
    """,
    """
@public
def foo():
    z: int128 = 2 + 3
    x: uint256(wei) = as_wei_value(2 + 3, "finney")
    """,
    """
@public
def foo():
    x: uint256(wei) = as_wei_value(5.182, "babbage")
    """,
    """
@public
def foo() -> uint256(wei):
    x: address = 0x1234567890123456789012345678901234567890
    return x.balance
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_as_wei_success(good_code):
    assert compiler.compile(good_code) is not None

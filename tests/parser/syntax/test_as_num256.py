import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def convert2(inp: num256) -> address:
    return convert(inp, 'bytes32')
    """,
    """
@public
def modtest(x: num256, y: num) -> num256:
    return x % y
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def convert1(inp: bytes32) -> num256:
    return convert(inp, 'num256')
    """,
    """
@public
def convert1(inp: bytes32) -> num256:
    return convert(inp, 'num256')
    """,
    """
@public
def convert2(inp: num256) -> bytes32:
    return convert(inp, 'bytes32')
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_as_wei_success(good_code):
    assert compiler.compile(good_code) is not None

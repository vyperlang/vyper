import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException

fail_list = [
    """
@public
def foo() -> uint256:
    return extract32("cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_extract32_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo() -> uint256:
    return extract32("cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0, type=uint256)
    """,
    """
x: bytes[100]
@public
def foo() -> uint256:
    self.x = "cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 0, type=uint256)
    """,
    """
x: bytes[100]
@public
def foo() -> uint256:
    self.x = "cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 1, type=uint256)
"""
]


@pytest.mark.parametrize('good_code', valid_list)
def test_extract32_success(good_code):
    assert compiler.compile_code(good_code) is not None

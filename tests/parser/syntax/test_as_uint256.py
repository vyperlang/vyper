import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

fail_list = [
    """
@public
def convert2(inp: uint256) -> uint256:
    return convert(inp, bytes32)
    """,
    """
@public
def modtest(x: uint256, y: int128) -> uint256:
    return x % y
    """,
    """
@private
def ret_non():
    pass

@public
def test():
    a: uint256 = 100 * self.ret_non()
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_uint256_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile_code(bad_code)

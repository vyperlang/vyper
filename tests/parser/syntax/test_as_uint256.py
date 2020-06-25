import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, TypeMismatch

fail_list = [
    (
        """
@public
def convert2(inp: uint256) -> uint256:
    return convert(inp, bytes32)
    """,
        TypeMismatch,
    ),
    (
        """
@public
def modtest(x: uint256, y: int128) -> uint256:
    return x % y
    """,
        TypeMismatch,
    ),
    (
        """
@private
def ret_non():
    pass

@public
def test():
    a: uint256 = 100 * self.ret_non()
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_as_uint256_fail(bad_code, exc):

    with pytest.raises(exc):
        compiler.compile_code(bad_code)

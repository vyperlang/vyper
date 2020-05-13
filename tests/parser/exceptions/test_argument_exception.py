import pytest

from vyper import compiler
from vyper.exceptions import ArgumentException

fail_list = [
    """
@public
def foo():
    x = as_wei_value(5, "vader")
    """,
    """
@public
def foo() -> int128:
    return as_wei_value(10)
    """,
    """
@public
def foo():
    x: bytes32 = keccak256("moose", 3)
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_literal_exception(bad_code):
    with pytest.raises(ArgumentException):
        compiler.compile_code(bad_code)

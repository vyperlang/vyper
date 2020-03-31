import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    InvalidLiteral,
    TypeMismatch,
)

fail_list = [
    ("""
@public
def foo(inp: bytes[10]) -> bytes[2]:
    return slice(inp, 2, 3)
    """, TypeMismatch),
    ("""
@public
def foo(inp: int128) -> bytes[3]:
    return slice(inp, 2, 3)
    """, TypeMismatch),
    ("""
@public
def foo(inp: bytes[10]) -> bytes[3]:
    return slice(inp, 4.0, 3)
    """, InvalidLiteral),
]


@pytest.mark.parametrize('bad_code,exc', fail_list)
def test_slice_fail(bad_code, exc):

    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo(inp: bytes[10]) -> bytes[3]:
    return slice(inp, 2, 3)
    """,
    """
@public
def foo(inp: bytes[10]) -> bytes[4]:
    return slice(inp, 2, 3)
    """,
    """
@public
def foo() -> bytes[10]:
    return slice(b"badmintonzzz", 1, 10)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_slice_success(good_code):
    assert compiler.compile_code(good_code) is not None

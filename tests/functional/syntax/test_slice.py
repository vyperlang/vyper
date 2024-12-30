import pytest

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo(inp: Bytes[10]) -> Bytes[2]:
    return slice(inp, 2, 3)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(inp: int128) -> Bytes[3]:
    return slice(inp, 2, 3)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(inp: Bytes[10]) -> Bytes[3]:
    return slice(inp, 4.0, 3)
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_slice_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo(inp: Bytes[10]) -> Bytes[3]:
    return slice(inp, 2, 3)
    """,
    """
@external
def foo(inp: Bytes[10]) -> Bytes[4]:
    return slice(inp, 2, 3)
    """,
    """
@external
def foo() -> Bytes[10]:
    return slice(b"badmintonzzz", 1, 10)
    """,
    # test constant folding for `slice()` `length` argument
    """
@external
def foo():
    x: Bytes[32] = slice(msg.data, 0, 31 + 1)
    """,
    """
@external
def foo(a: address):
    x: Bytes[32] = slice(a.code, 0, 31 + 1)
    """,
    """
@external
def foo(inp: Bytes[5], start: uint256) -> Bytes[3]:
    return slice(inp, 0, 1 + 1)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_slice_success(good_code):
    assert compiler.compile_code(good_code) is not None

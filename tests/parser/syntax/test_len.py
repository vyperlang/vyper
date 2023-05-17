import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    """
@external
def foo(inp: Bytes[4]) -> int128:
    return len(inp)
    """,
    """
@external
def foo(inp: int128) -> uint256:
    return len(inp)
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo(inp: Bytes[10]) -> uint256:
    return len(inp)
    """,
    """
@external
def foo(inp: String[10]) -> uint256:
    return len(inp)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_list_success(good_code):
    assert compiler.compile_code(good_code) is not None

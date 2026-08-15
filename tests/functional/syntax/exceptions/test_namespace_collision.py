import pytest

from vyper import compiler
from vyper.exceptions import NamespaceCollision

fail_list = [
    """
@external
def foo(int128: int128):
    pass
    """,
    """
@external
def foo():
    x: int128 = 12
@external
def foo():
    y: int128 = 12
    """,
    """
foo: int128

@external
def foo():
    pass
    """,
    """
x: int128
x: int128
    """,
    """
@external
def foo():
    x: int128 = 0
    x: int128 = 0
    """,
    """
@external
def foo():
    msg: bool = True
    """,
    """
int128: Bytes[3]
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_insufficient_arguments(bad_code):
    with pytest.raises(NamespaceCollision):
        compiler.compile_code(bad_code)


pass_list = [
    """
x: int128

@external
def foo(x: int128): pass
    """,
    """
x: int128

@external
def foo():
    x: int128 = 1234
    """,
]


@pytest.mark.parametrize("code", pass_list)
def test_valid(code):
    compiler.compile_code(code)

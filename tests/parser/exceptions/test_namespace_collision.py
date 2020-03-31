import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    NamespaceCollision,
)

fail_list = [
    """
@public
def foo(int128: int128):
    pass
    """,
    """
@public
def foo():
    x: int128 = 12
@public
def foo():
    y: int128 = 12
    """,
    """
foo: int128

@public
def foo():
    pass
    """,
    """
x: int128

@public
def foo(x: int128): pass
    """,
    """
x: int128
x: int128
    """,
    """
@public
def foo():
    x: int128 = 0
    x: int128 = 0
    """,
    """
@public
def foo():
    msg: bool = True
    """,
    """
@public
def foo():
    struct: bool = True
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_insufficient_arguments(bad_code):
    with pytest.raises(NamespaceCollision):
        compiler.compile_code(bad_code)

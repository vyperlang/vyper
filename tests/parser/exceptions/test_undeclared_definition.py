import pytest

from vyper import compiler
from vyper.exceptions import UndeclaredDefinition

fail_list = [
    """
@public
def test1(b: uint256) -> uint256:
    a: uint256 = a + b
    return a
    """,
    """
@public
def test2(b: uint256, c: uint256) -> uint256:
    a: uint256 = a + b + c
    return a
    """,
    """
@public
def test3(b: int128, c: int128) -> int128:
    a: int128 = - a
    return a
    """,
    """
@public
def test4(b: bool) -> bool:
    a: bool = b or a
    return a
    """,
    """
@public
def test5(b: bool) -> bool:
    a: bool = a != b
    return a
    """,
    """
@public
def test6(b:bool, c: bool) -> bool:
    a: bool = (a and b) and c
    return a
    """,
    """
@public
def foo():
    throe = 2
    """,
    """
@public
def foo():
    x: int128 = bar(55)
    """,
    """
@public
def foo():
    x = 5
    x: int128 = 0
    """,
    """
@public
def foo():
    bork = zork
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_undeclared_def_exception(bad_code):
    with pytest.raises(UndeclaredDefinition):
        compiler.compile_code(bad_code)

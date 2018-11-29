import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException, StructureException


fail_list = [
    """
bar: int128[3][3]
@public
def foo():
    self.bar = [[1, 2], [3, 4, 5], [6, 7, 8]]
    """,
    """
bar: int128[3][3]
@public
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7.0, 8.0, 9.0]]
    """,
    """
@public
def foo() -> int128[2]:
    return [[1,2],[3,4]]
    """,
    """
@public
def foo() -> int128[2][2]:
    return [1,2]
    """,
    """
y: address[2][2]

@public
def foo(x: int128[2][2]) -> int128:
    self.y = x
    """,
    ("""
bar: int128[3][3]

@public
def foo() -> int128[3]:
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    for x in self.bar:
        if x == [4, 5, 6]:
            return x
    """, StructureException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_nested_list_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile_code(bad_code)


valid_list = [
    """
bar: int128[3][3]
@public
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    """,
    """
bar: decimal[3][3]
@public
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_nested_list_sucess(good_code):
    assert compiler.compile_code(good_code) is not None

import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException, StructureException


fail_list = [
    """
bar: num[3][3]
@public
def foo():
    self.bar = [[1, 2], [3, 4, 5], [6, 7, 8]]
    """,
    """
bar: num[3][3]
@public
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7.0, 8.0, 9.0]]
    """,
    """
@public
def foo() -> num[2]:
    return [[1,2],[3,4]]
    """,
    """
@public
def foo() -> num[2][2]:
    return [1,2]
    """,
    """
y: address[2][2]

@public
def foo(x: num[2][2]) -> num:
    self.y = x
    """,
    ("""
bar: num[3][3]

@public
def foo() -> num[3]:
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
            compiler.compile(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
bar: num[3][3]
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
    assert compiler.compile(good_code) is not None

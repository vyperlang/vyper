import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
bar: num[3][3]
def foo():
    self.bar = [[1, 2], [3, 4, 5], [6, 7, 8]]
    """,
    """
bar: num[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9.0]]
    """,
    """
def foo() -> num[2]:
    return [[1,2],[3,4]]
    """,
    """
def foo() -> num[2][2]:
    return [1,2]
    """,
    """
y: address[2][2]

def foo(x: num[2][2]) -> num:
    self.y = x
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_nested_list_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
bar: num[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    """,
    """
bar: decimal[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9.0]]
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_nested_list_sucess(good_code):
    assert compiler.compile(good_code) is not None

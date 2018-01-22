
import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import VariableDeclarationException


fail_list = [
    """
@public
def foo(choice: bool):
    if (choice):
        a = 1
    a += 1
    """,
    """
@public
def foo(choice: bool):
    if (choice):
        a = 0
    else:
        a = 1
    a += 1
    """,
    """
@public
def foo(choice: bool):
    if (choice):
        a = 0
    else:
        a += 1
    """,
    """
@public
def foo(choice: bool):

    for i in range(4):
        a = 0
    a += 1
    """,
    """
@public
def foo(choice: bool):

    for i in range(4):
        a = 0
    a += 1
    """,
    """
a: num

@public
def foo():
    a = 5
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_fail_(bad_code):

    with raises(VariableDeclarationException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo(choice: bool, choice2: bool):
    if (choice):
        a: num = 11
        if choice2 and a > 1:
            a -= 1  # should be visible here.
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_valid_blockscope(good_code):
    assert compiler.compile(good_code) is not None

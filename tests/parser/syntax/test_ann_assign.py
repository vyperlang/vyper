import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import VariableDeclarationException, TypeMismatchException


fail_list = [
    """
@public
def test():
    a = 1
    """,
    """
@public
def test():
    a = 33.33
    """,
    """
@public
def test():
    a = "test string"
    """,
    ("""
@public
def test():
    a: num = 33.33
    """, TypeMismatchException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile(bad_code[0])
    else:
        with raises(VariableDeclarationException):
            compiler.compile(bad_code)


valid_list = [
    """
@public
def test():
    a: num = 1
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_ann_assign_success(good_code):
    assert compiler.compile(good_code) is not None

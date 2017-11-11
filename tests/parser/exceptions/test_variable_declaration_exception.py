import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import VariableDeclarationException


fail_list = [
    """
x: num
x: num
    """,
    """
x: num

@public
def foo(x: num): pass
    """,
    """
@public
def foo(x: num, x: num): pass
    """,
    """
@public
def foo(num: num):
    pass
    """,
    """
@public
def foo():
    x = 5
    x: num
    """,
    """
@public
def foo():
    x: num
    x: num
    """,
    """
@public
def foo():
    x: num
@public
def foo():
    y: num
    """,
    """
@public
def foo():
    num = 5
    """,
    """
@public
def foo():
    bork = zork
    """,

    """
x: num
@public
def foo():
    x = 5
    """,
    """
b: num
@public
def foo():
    b = 7
    """,
    """
x: wei_value

@public
def foo():
    send(0x1234567890123456789012345678901234567890, x)
    """,
    """
@public
def foo():
    true = 3
    """,
    """
@public
def foo():
    self.goo()

@public
def goo():
    self.foo()
    """,
    """
@public
def foo():
    BALANCE = 45
    """,
    """
num: num
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_decleration_exception(bad_code):
        with raises(VariableDeclarationException):
            compiler.compile(bad_code)

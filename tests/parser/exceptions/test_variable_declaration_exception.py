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

def foo(x: num): pass
    """,
    """
def foo(x: num, x: num): pass
    """,
    """
def foo(num: num):
    pass
    """,
    """
def foo():
    x = 5
    x: num
    """,
    """
def foo():
    x: num
    x: num
    """,
    """
def foo():
    x: num
def foo():
    y: num
    """,
    """
def foo():
    num = 5
    """,
    """
def foo():
    bork = zork
    """,

    """
x: num
def foo():
    x = 5
    """,
    """
b: num
def foo():
    b = 7
    """,
    """
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, x)
    """,
    """
def foo():
    true = 3
    """,
    """
def foo():
    self.goo()

def goo():
    self.foo()
    """,
    """
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

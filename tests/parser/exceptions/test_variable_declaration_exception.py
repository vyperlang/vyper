import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import VariableDeclarationException


fail_list = [
    """
x: int128
x: int128
    """,
    """
x: int128

@public
def foo(x: int128): pass
    """,
    """
@public
def foo(x: int128, x: int128): pass
    """,
    """
@public
def foo(int128: int128):
    pass
    """,
    """
@public
def foo():
    x = 5
    x: int128
    """,
    """
@public
def foo():
    x: int128
    x: int128
    """,
    """
@public
def foo():
    x: int128
@public
def foo():
    y: int128
    """,
    """
@public
def foo():
    int128 = 5
    """,
    """
@public
def foo():
    bork = zork
    """,

    """
x: int128
@public
def foo():
    x = 5
    """,
    """
b: int128
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
foo: int128

@public
def foo():
    pass
    """,
    """
CALLDATACOPY: int128
    """,
    """
int128: bytes[3]
    """,
    """
sec: int128
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_decleration_exception(bad_code):
        with raises(VariableDeclarationException):
            compiler.compile(bad_code)

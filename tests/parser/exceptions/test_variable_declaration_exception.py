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
CALLDATACOPY: int128
    """,
    """
int128: bytes[3]
    """,
    """
sec: int128
    """,
    """
@public
def foo():
    BALANCE = 45
    """,
    """
@public
def foo():
    true = 3
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
    int128 = 5
    """,
    """
@public
def foo():
    bork = zork
    """,
    """
b: int128
@public
def foo():
    b = 7
    """,
    """
x: int128
@public
def foo():
    x = 5
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_declaration_exception(bad_code):
        with raises(VariableDeclarationException):
            compiler.compile(bad_code)

import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def foo():
    send(1, 2)
    """,
    """
def foo():
    send(1, 2)
    """,
    """
def foo():
    send(0x1234567890123456789012345678901234567890, 2.5)
    """,
    """
def foo():
    send(0x1234567890123456789012345678901234567890, 0x1234567890123456789012345678901234567890)
    """,
    """
x: num

def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
    """
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1.5)
    """,
    """
x: decimal

def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_send_fail(bad_code):
    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1)
    """,
    """
x: decimal

def foo():
    send(0x1234567890123456789012345678901234567890, as_wei_value(floor(self.x), wei))
    """,
    """
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
    """
def foo():
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 5)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None

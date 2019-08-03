import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

fail_list = [
    """
@public
def foo():
    send(1, 2)
    """,
    """
@public
def foo():
    send(1, 2)
    """,
    """
@public
def foo():
    send(0x1234567890123456789012345678901234567890, 2.5)
    """,
    """
@public
def foo():
    send(0x1234567890123456789012345678901234567890, 0x1234567890123456789012345678901234567890)
    """,
    """
x: int128

@public
def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
    """
x: wei_value

@public
def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1.5)
    """,
    """
x: decimal

@public
def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_send_fail(bad_code):
    with raises(TypeMismatchException):
        compiler.compile_code(bad_code)


valid_list = [
    """
x: wei_value

@public
def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1)
    """,
    """
x: decimal

@public
def foo():
    send(0x1234567890123456789012345678901234567890, as_wei_value(floor(self.x), "wei"))
    """,
    """
x: wei_value

@public
def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
    """
@public
def foo():
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 5)
    """,
    """
# Test custom send method
@private
def send(a: address, w: wei_value):
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 1)

@public
@payable
def foo():
    self.send(msg.sender, msg.value)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None

import pytest

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    send(1, 2)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    send(0x1234567890123456789012345678901234567890, 2.5)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    send(0x1234567890123456789012345678901234567890, 0x1234567890123456789012345678901234567890)
    """,
        TypeMismatch,
    ),
    (
        """
x: int128

@external
def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
        TypeMismatch,
    ),
    (
        """
x: uint256

@external
def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1.5)
    """,
        TypeMismatch,
    ),
    (
        """
x: decimal

@external
def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
        TypeMismatch,
    ),
    # Tests for sending gas stipend
    (
        """
@external
def foo():
    send(0x1234567890123456789012345678901234567890, 5, gas=1.5)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    send(0x1234567890123456789012345678901234567890, 5, gas=-2)
    """,
        TypeMismatch,
    ),
    (
        """
x: int128

@external
def foo():
    send(0x1234567890123456789012345678901234567890, 5, gas=self.x)
    """,
        TypeMismatch,
    ),
    (
        """
x: decimal

@external
def foo():
    send(0x1234567890123456789012345678901234567890, 5, gas=self.x)
    """,
        TypeMismatch,
    ),
    # End tests for sending gas stipend
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_send_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
x: uint256

@external
def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1)
    """,
    """
x: decimal

@external
def foo():
    send(
        0x1234567890123456789012345678901234567890,
        as_wei_value(convert(floor(self.x), int128),
        "wei")
    )
    """,
    """
x: uint256

@external
def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
    """,
    """
@external
def foo():
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 5)
    """,
    """
# Test custom send method
@internal
def send(a: address, w: uint256):
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 1)

@external
@payable
def foo():
    self.send(msg.sender, msg.value)
    """,
    """
#Test send gas stipend
@external
def foo():
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 5, gas=5000)
    """,
    """
x: uint256

#Test send gas stipend
@external
def foo():
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 5, gas=self.x)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None

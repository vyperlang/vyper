import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    ImmutableViolation,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
)

fail_list = [
    (
        """
@public
def test():
    a: int128 = 0
    b: int128 = 0
    c: int128 = 0
    a, b, c = 1, 2, 3
    """,
        StructureException,
    ),
    """
@private
def out_literals() -> (int128, int128, bytes[10]):
    return 1, 2, b"3333"

@public
def test() -> (int128, address, bytes[10]):
    a: int128 = 0
    b: int128 = 0
    a, b, b = self.out_literals()  # incorrect bytes type
    return a, b, c
    """,
    """
@private
def out_literals() -> (int128, int128, bytes[10]):
    return 1, 2, b"3333"

@public
def test() -> (int128, address, bytes[10]):
    a: int128 = 0
    b: address = ZERO_ADDRESS
    a, b = self.out_literals()  # tuple count mismatch
    return
    """,
    """
@private
def out_literals() -> (int128, int128, int128):
    return 1, 2, 3

@public
def test() -> (int128, int128, bytes[10]):
    a: int128 = 0
    b: int128 = 0
    c: bytes[10] = b""
    a, b, c = self.out_literals()
    return a, b, c
    """,
    """
@private
def out_literals() -> (int128, int128, bytes[100]):
    return 1, 2, b"test"

@public
def test():
    a: int128 = 0
    b: int128 = 0
    c: bytes[1] = b""
    a, b, c = self.out_literals()
    """,
    (
        """
@private
def _test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1000
    return a, b, -1200

@public
def test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1
    c: int128 = 1
    d: int128 = 123
    a, b, c = self._test(a)
    assert d == 123
    return a, b, c
    """,
        ImmutableViolation,
    ),
    (
        """
x: public(uint256)

@private
@view
def return_two() -> (uint256, uint256):
    return 1, 2

@public
@view
def foo():
    a: uint256 = 0
    a, self.x = self.return_two()
     """,
        StateAccessViolation,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_tuple_assign_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)

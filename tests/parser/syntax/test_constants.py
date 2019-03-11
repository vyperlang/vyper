import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    FunctionDeclarationException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)

fail_list = [
    # no value
    """
VAL: constant(uint256)
    """,
    # too many args
    """
VAL: constant(uint256, int128) = 12
    """,
    # invalid type
    ("""
VAL: constant(uint256) = "test"
    """, TypeMismatchException),
    # invalid range
    ("""
VAL: constant(uint256) = -1
    """, TypeMismatchException),
    # reserverd keyword
    ("""
wei: constant(uint256) = 1
    """, VariableDeclarationException),
    # duplicate constant name
    ("""
VAL: constant(uint256) = 11
VAL: constant(uint256) = 11
    """, VariableDeclarationException),
    # bytearray too long.
    ("""
VAL: constant(bytes[4]) = b"testtest"
    """, TypeMismatchException),
    # global with same name
    ("""
VAL: constant(bytes[4]) = b"t"
VAL: uint256
    """, VariableDeclarationException),
    # signature variable with same name
    ("""
VAL: constant(bytes[4]) = b"t"

@public
def test(VAL: uint256):
    pass
    """, FunctionDeclarationException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(StructureException):
            compiler.compile_code(bad_code)


valid_list = [
    """
VAL: constant(uint256) = 123
    """,
    """
VAL: constant(int128) = -123
@public
def test() -> int128:
    return 1 * VAL
    """,
    """
TREE_FIDDY: constant(uint256(wei))  = as_wei_value(350, 'ether')
    """
    """
FOO: constant(int128) = 100
    """,
    """
test_a : constant(uint256) = 21888242871839275222246405745257275088696311157297823662689037894645226208583  # noqa: E501
    """,
    """
test_a : constant(int128) = 2188824287183927522224640574525
    """,
    """
test_a: constant(uint256) = MAX_UINT256
    """,
    """
TEST_C: constant(int128) = 1
TEST_WEI: constant(uint256(wei)) = 1

@private
def test():
   raw_call(0x0000000000000000000000000000000000000005, b'hello', outsize=TEST_C, gas=2000)

@private
def test1():
    raw_call(0x0000000000000000000000000000000000000005, b'hello', outsize=256, gas=TEST_WEI)
    """,
    """
LIMIT: constant(int128) = 1

myEvent: event({arg1: bytes32[LIMIT]})
    """,
    """
CONST: constant(uint256) = 8

@public
@constant
def test():
    for i in range(CONST / 4):
        pass
    """,
    """
MIN_DEPOSIT: constant(uint256) = 1  # ETH
MAX_DEPOSIT: constant(decimal) = 32.0  # ETH

@payable
@public
def deposit(deposit_input: bytes[2048]):
    assert msg.value >= as_wei_value(MIN_DEPOSIT, "ether")
    assert msg.value <= as_wei_value(MAX_DEPOSIT, "ether")
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_as_wei_success(good_code):
    assert compiler.compile_code(good_code) is not None

import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    ArgumentException,
    ConstancyViolation,
    InvalidType,
    NamespaceCollision,
    StructureException,
    VariableDeclarationException,
)

fail_list = [
    # no value
    (
        """
VAL: constant(uint256)
    """,
        VariableDeclarationException,
    ),
    # too many args
    (
        """
VAL: constant(uint256, int128) = 12
    """,
        ArgumentException,
    ),
    # invalid type
    (
        """
VAL: constant(uint256) = "test"
    """,
        InvalidType,
    ),
    # invalid range
    (
        """
VAL: constant(uint256) = -1
    """,
        InvalidType,
    ),
    # reserverd keyword
    (
        """
wei: constant(uint256) = 1
    """,
        VariableDeclarationException,
    ),
    # duplicate constant name
    (
        """
VAL: constant(uint256) = 11
VAL: constant(uint256) = 11
    """,
        NamespaceCollision,
    ),
    # bytearray too long.
    (
        """
VAL: constant(bytes[4]) = b"testtest"
    """,
        InvalidType,
    ),
    # global with same name
    (
        """
VAL: constant(bytes[4]) = b"t"
VAL: uint256
    """,
        VariableDeclarationException,
    ),
    # signature variable with same name
    (
        """
VAL: constant(bytes[4]) = b"t"

@public
def test(VAL: uint256):
    pass
    """,
        NamespaceCollision,
    ),
    (
        """
C1: constant(uint256) = block.number
    """,
        ConstancyViolation,
    ),
    # cannot assign function result to a constant
    (
        """
@public
def foo() -> uint256:
    return 42

c1: constant(uint256) = self.foo
     """,
        ConstancyViolation,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_constants_fail(bad_code):
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
TREE_FIDDY: constant(uint256) = as_wei_value(350, 'ether')
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
TEST_WEI: constant(uint256) = 1

@private
def test():
   foo: bytes[1] = raw_call(
       0x0000000000000000000000000000000000000005, b'hello', max_outsize=TEST_C, gas=2000
    )

@private
def test1():
    foo: bytes[256] = raw_call(
        0x0000000000000000000000000000000000000005, b'hello', max_outsize=256, gas=TEST_WEI
    )
    """,
    """
LIMIT: constant(int128) = 1

myEvent: event({arg1: bytes32[LIMIT]})
    """,
    """
CONST: constant(uint256) = 8

@public
@view
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
    """,
    """
BYTE32_LIST: constant(bytes32[2]) = [
    0x0000000000000000000000000000000000000000000000000000000000000321,
    0x0000000000000000000000000000000000000000000000000000000000000123
]
    """,
    """
ZERO_LIST: constant(int128[8]) = [0, 0, 0, 0, 0, 0, 0, 0]
    """,
    """
MY_DECIMAL: constant(decimal) = 1e-10
    """,
    """
MY_DECIMAL: constant(decimal) = -1e38
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_constant_success(good_code):
    assert compiler.compile_code(good_code) is not None

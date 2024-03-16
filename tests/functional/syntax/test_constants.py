import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    ArgumentException,
    ImmutableViolation,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
    SyntaxException,
    TypeMismatch,
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
        TypeMismatch,
    ),
    # invalid range
    (
        """
VAL: constant(uint256) = -1
    """,
        TypeMismatch,
    ),
    # reserved keyword
    (
        """
wei: constant(uint256) = 1
    """,
        StructureException,
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
VAL: constant(Bytes[4]) = b"testtest"
    """,
        TypeMismatch,
    ),
    # global with same name
    (
        """
VAL: constant(Bytes[4]) = b"t"
VAL: uint256
    """,
        NamespaceCollision,
    ),
    # global with same type and name
    (
        """
VAL: constant(uint256) = 1
VAL: uint256
    """,
        NamespaceCollision,
    ),
    # global with same type and name, different order
    (
        """
VAL: uint256
VAL: constant(uint256) = 1
    """,
        NamespaceCollision,
    ),
    # global with same type and name
    (
        """
VAL: immutable(uint256)
VAL: uint256

@deploy
def __init__():
    VAL = 1
    """,
        NamespaceCollision,
    ),
    # global with same type and name, different order
    (
        """
VAL: uint256
VAL: immutable(uint256)

@deploy
def __init__():
    VAL = 1
    """,
        NamespaceCollision,
    ),
    # signature variable with same name
    (
        """
VAL: constant(Bytes[4]) = b"t"

@external
def test(VAL: uint256):
    pass
    """,
        NamespaceCollision,
    ),
    (
        """
C1: constant(uint256) = block.number
    """,
        StateAccessViolation,
    ),
    (
        """
struct Foo:
    a: uint256
    b: uint256

CONST_BAR: constant(Foo) = Foo(a=1, b=block.number)
    """,
        StateAccessViolation,
    ),
    # cannot assign function result to a constant
    (
        """
@internal
def foo() -> uint256:
    return 42

c1: constant(uint256) = self.foo()
     """,
        StateAccessViolation,
    ),
    (
        # constant(public()) banned
        """
S: constant(public(uint256)) = 3
    """,
        SyntaxException,
    ),
    # cannot re-assign constant value
    (
        """
struct Foo:
    a : uint256

x: constant(Foo) = Foo(a=1)

@external
def hello() :
    x.a =  2
    """,
        ImmutableViolation,
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
@external
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
test_a: constant(uint256) = max_value(uint256)
    """,
    """
test_a: constant(address) = empty(address)
    """,
    """
TEST_C: constant(uint256) = 1
TEST_WEI: constant(uint256) = 1

@internal
def test():
   foo: Bytes[1] = raw_call(
       0x0000000000000000000000000000000000000005, b'hello', max_outsize=TEST_C, gas=2000
    )

@internal
def test1():
    foo: Bytes[256] = raw_call(
        0x0000000000000000000000000000000000000005, b'hello', max_outsize=256, gas=TEST_WEI
    )
    """,
    """
LIMIT: constant(int128) = 1

event myEvent:
    arg1: bytes32[LIMIT]
    """,
    """
CONST: constant(uint256) = 8

@external
@view
def test():
    for i: uint256 in range(CONST // 4):
        pass
    """,
    """
MIN_DEPOSIT: constant(uint256) = 1  # ETH
MAX_DEPOSIT: constant(decimal) = 32.0  # ETH

@payable
@external
def deposit(deposit_input: Bytes[2048]):
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
    """
CONST_BYTES: constant(Bytes[4]) = b'1234'
    """,
    """
struct Foo:
    a: uint256
    b: uint256

CONST_BAR: constant(Foo) = Foo(a=1, b=2)
    """,
    """
CONST_EMPTY: constant(bytes32) = empty(bytes32)

@internal
def foo() -> bytes32:
    return CONST_EMPTY
    """,
    """
struct Foo:
    a: uint256
    b: uint256

A: constant(uint256) = 1
B: constant(uint256) = 2

CONST_BAR: constant(Foo) = Foo(a=A, b=B)
    """,
    """
struct Foo:
    a: uint256
    b: uint256

struct Bar:
    c: Foo
    d: int128

A: constant(uint256) = 1
B: constant(uint256) = 2
C: constant(Foo) = Foo(a=A, b=B)
D: constant(int128) = -1

CONST_BAR: constant(Bar) = Bar(c=C, d=D)
    """,
    """
interface Foo:
    def foo(): nonpayable

FOO: constant(Foo) = Foo(0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF)
    """,
    """
interface Foo:
    def foo(): nonpayable

FOO: constant(Foo) = Foo(BAR)
BAR: constant(address) = 0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_constant_success(good_code):
    assert compiler.compile_code(good_code) is not None

import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
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
VAL: constant(bytes[4]) = "testtest"
    """, TypeMismatchException),
    # global with same name
    ("""
VAL: constant(bytes[4]) = "t"
VAL: uint256
    """, VariableDeclarationException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile(bad_code[0])
    else:
        with raises(StructureException):
            compiler.compile(bad_code)


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
TREE_FIDDY: constant(uint256)  = 350

@public
def a(a: uint256) -> bool:
    for i in range(TREE_FIDDY):
        if i <= a:
            return True
    return False
    """,
    """
VAL: constant(uint256) = as_wei_value(123, "ether")
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_as_wei_success(good_code):
    assert compiler.compile(good_code) is not None

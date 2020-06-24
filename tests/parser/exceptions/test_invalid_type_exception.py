import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidType, UnknownType

fail_list = [
    """
x: bat
    """,
    """
x: map(int, int128)
    """,
    """
x: [bar, baz]
    """,
    """
x: [bar(int128), baz(baffle)]
    """,
    """
struct A:
    b: B
struct B:
    a: A
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_unknown_type_exception(bad_code):
    with raises(UnknownType):
        compiler.compile_code(bad_code)


invalid_list = [
    """
@public
def foo():
    raw_log(b"cow", b"dog")
    """,
    # Must be a literal string.
    """
@public
def mint(_to: address, _value: uint256):
    assert msg.sender == self,minter
    """,
    # Raise reason must be string
    """
@public
def mint(_to: address, _value: uint256):
    raise 1
    """,
    """
x: int128[3.5]
    """,
]


@pytest.mark.parametrize('bad_code', invalid_list)
def test_invalid_type_exception(bad_code):
    with raises(InvalidType):
        compiler.compile_code(bad_code)

import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    """
@external
def foo():
    a: uint256 = 3
    b: int128 = 4
    c: uint256 = min(a, b)
    """,
    """
@external
def broken():
    a : uint256 = 3
    b : int128 = 4
    c : uint256 = unsafe_add(a, b)
    """,
    """
@external
def foo():
    b: Bytes[1] = b"\x05"
    x: uint256 = as_wei_value(b, "babbage")
    """,
    """
@external
def foo():
    raw_log(b"cow", b"dog")
    """,
    """
@external
def foo():
    xs: uint256[1] = []
    """,
    # literal longer than event member
    """
event Foo:
    message: String[1]
@external
def foo():
    log Foo("abcd")
    """,
    # Address literal must be checksummed
    """
a: constant(address) = 0x3cd751e6b0078be393132286c442345e5dc49699
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_type_mismatch_exception(bad_code):
    with raises(TypeMismatch):
        compiler.compile_code(bad_code)

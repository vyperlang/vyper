import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import SyntaxException, TypeMismatch

fail_list = [
    """
@public
def baa():
    x: bytes[50] = b""
    y: bytes[50] = b""
    z = x + y
    """,
    """
@public
def baa():
    x: bytes[50] = b""
    y: int128 = 0
    y = x
    """,
    """
@public
def baa():
    x: bytes[50] = b""
    y: int128 = 0
    x = y
    """,
    """
@public
def baa():
    x: bytes[50] = b""
    y: bytes[60] = b""
    x = y
    """,
    """
@public
def foo(x: bytes[100]) -> bytes[75]:
    return x
    """,
    """
@public
def foo(x: bytes[100]) -> int128:
    return x
    """,
    """
@public
def foo(x: int128) -> bytes[75]:
    return x
    """,
    """
@public
def foo() -> bytes[10]:
    x: bytes[10] = '0x1234567890123456789012345678901234567890'
    x = 0x1234567890123456789012345678901234567890
    return x
    """,
    """
@public
def foo() -> bytes[10]:
    return "badmintonzz"
    """,
    ("""
@public
def test() -> bytes[1]:
    a: bytes[1] = 0b0000001  # needs multiple of 8 bits.
    return a
    """, SyntaxException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_bytes_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo(x: bytes[100]) -> bytes[100]:
    return x
    """,
    """
@public
def foo(x: bytes[100]) -> bytes[150]:
    return x
    """,
    """
@public
def baa():
    x: bytes[50] = b""
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_bytes_success(good_code):
    assert compiler.compile_code(good_code) is not None

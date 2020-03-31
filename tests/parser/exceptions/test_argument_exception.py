import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    ArgumentException,
)

fail_list = [
    """
@public
def foo(x: int128, x: int128): pass
    """,
    """
@public
def foo(x): pass
    """,
    """
@public
def foo() -> int128:
    return as_wei_value(10)
    """,
    """
@public
def foo():
    x: bytes32 = keccak256("moose", 3)
    """,
    """
@public
def foo():
    x: bytes[4] = raw_call(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
@public
def foo():
    x: bytes[4] = raw_call(
        0x1234567890123456789012345678901234567890, b"cow", gas=111111, outsize=4, moose=9
    )
    """,
    """
@public
def foo():
    x: bytes[4] = create_forwarder_to(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
x: public()
    """,
    """
@public
def foo():
    raw_log([], b"cow", "dog")
    """,
    """
@public
def foo():
    x: bytes[10] = concat(b"")
    """,
    """
struct S:
    x: int128
s: S = S({x: int128}, 1)
    """,
    """
struct S:
    x: int128
s: S = S()
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_function_declaration_exception(bad_code):
    with raises(ArgumentException):
        compiler.compile_code(bad_code)

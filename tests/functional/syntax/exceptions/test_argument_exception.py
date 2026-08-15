import pytest

from vyper import compile_code
from vyper.exceptions import ArgumentException

fail_list = [
    """
@external
def foo():
    x: uint256 = as_wei_value(5, "vader")
    """,
    """
@external
def foo(x: int128, x: int128): pass
    """,
    """
@external
def foo(x): pass
    """,
    """
@external
def foo() -> int128:
    return as_wei_value(10)
    """,
    """
@external
def foo():
    x: bytes32 = keccak256("moose", 3)
    """,
    """
@external
def foo():
    x: Bytes[4] = raw_call(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
@external
def foo():
    x: Bytes[4] = raw_call(
        0x1234567890123456789012345678901234567890, b"cow", gas=111111, outsize=4, moose=9
    )
    """,
    """
@external
def foo():
    x: Bytes[4] = create_minimal_proxy_to(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
x: public()
    """,
    """
@external
def foo():
    raw_log([], b"cow", "dog")
    """,
    """
@external
def foo():
    x: Bytes[10] = concat(b"")
    """,
    """
@external
def foo():
    x: Bytes[4] = create_minimal_proxy_to(0x1234567890123456789012345678901234567890, b"cow")
    """,
    """
@external
def foo():
    a: uint256 = min()
    """,
    """
@external
def foo():
    a: uint256 = min(1)
    """,
    """
@external
def foo():
    a: uint256 = min(1, 2, 3)
    """,
    """
@external
def foo():
    for i: uint256 in range():
        pass
    """,
    """
@external
def foo():
    for i: uint256 in range(1, 2, 3, 4):
        pass
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_function_declaration_exception(bad_code):
    with pytest.raises(ArgumentException):
        compile_code(bad_code)

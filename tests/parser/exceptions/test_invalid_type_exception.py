import pytest

from vyper.exceptions import InvalidType, UnknownType

fail_list = [
    """
x: bat
    """,
    """
x: HashMap[int, int128]
    """,
    """
struct A:
    b: B
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_unknown_type_exception(bad_code, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), UnknownType)


invalid_list = [
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
    # Must be a literal string.
    """
@external
def mint(_to: address, _value: uint256):
    assert msg.sender == self,msg.sender
    """,
    # literal longer than event member
    """
event Foo:
    message: String[1]
@external
def foo():
    log Foo("abcd")
    """,
    # Raise reason must be string
    """
@external
def mint(_to: address, _value: uint256):
    raise 1
    """,
    """
x: int128[3.5]
    """,
    # Key of mapping must be a base type
    """
b: HashMap[(int128, decimal), int128]
    """,
    # Address literal must be checksummed
    """
a: constant(address) = 0x3cd751e6b0078be393132286c442345e5dc49699
    """,
    """
x: String <= 33
    """,
    """
x: Bytes <= wei
    """,
    """
x: 5
    """,
]


@pytest.mark.parametrize("bad_code", invalid_list)
def test_invalid_type_exception(bad_code, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), InvalidType)

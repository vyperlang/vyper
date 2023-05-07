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
    """
event Foo:
    a: uint256

@external
def foo() -> Foo:
    return Foo(2)
    """,
    """
event Foo:
    a: uint256

@external
def foo() -> (uint256, Foo):
    return 1, Foo(2)
    """,
    """
a: HashMap[uint256, uint256]

@external
def foo() -> HashMap[uint256, uint256]:
    return self.a
    """,
    """
event Foo:
    a: uint256

@external
def foo(x: Foo):
    pass
    """,
    """
@external
def foo(x: HashMap[uint256, uint256]):
    pass
    """,
    """
@external
def foo(x: (uint256, uint256)):
    pass
    """,
    """
event Foo:
    a: uint256

foo: Foo
    """,
    """
event Foo:
    a: uint256

@external
def foo():
    f: Foo = Foo(1)
    pass
    """,
    """
event Foo:
    a: uint256

b: HashMap[uint256, Foo]
    """,
    """
event Foo:
    a: uint256

b: HashMap[Foo, uint256]
    """,
    """
b: immutable(HashMap[uint256, uint256])

@external
def __init__():
    b = empty(HashMap[uint256, uint256])
    """,
    """
b: immutable((uint256, uint256))

@external
def __init__():
    b = (0, 0)
    """,
]


@pytest.mark.parametrize("bad_code", invalid_list)
def test_invalid_type_exception(bad_code, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), InvalidType)

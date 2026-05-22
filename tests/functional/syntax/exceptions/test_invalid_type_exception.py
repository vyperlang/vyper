import pytest

from vyper.builtins.functions import BUILTIN_FUNCTIONS
from vyper.exceptions import InvalidType, UnknownType
from vyper.semantics.environment import CONSTANT_ENVIRONMENT_VARS, MUTABLE_ENVIRONMENT_VARS

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
    """
v: uint256
x: v # unknown type because to refer to `v` it would be `self.v`
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_unknown_type_exception(bad_code, get_contract):
    with pytest.raises(UnknownType):
        get_contract(bad_code)


invalid_list = [
    # Must be a literal string.
    """
@external
def mint(_to: address, _value: uint256):
    assert msg.sender == self,msg.sender
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
v: constant(uint256) = 0
x: v
    """,
    """
v: uint256

def foo():
    x: self.v = 0
    """,
    # environment variables and builtin functions used as types should be invalid
    *[f"x: {name}" for name in CONSTANT_ENVIRONMENT_VARS],
    *[f"x: {name}" for name in MUTABLE_ENVIRONMENT_VARS],
    *[f"x: {name}" for name in BUILTIN_FUNCTIONS],
]


@pytest.mark.parametrize("bad_code", invalid_list)
def test_invalid_type_exception(bad_code, get_contract):
    with pytest.raises(InvalidType):
        get_contract(bad_code)

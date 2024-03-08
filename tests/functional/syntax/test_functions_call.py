import pytest

from vyper import compiler
from vyper.exceptions import StructureException, UndeclaredDefinition, UnknownAttribute

fail_list = [
    (
        """
@external
def foo() -> uint256:
    doesnotexist(2, uint256)
    return convert(2, uint256)
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def foo(x: int256) -> uint256:
    convert(x, uint256)
    return convert(x, uint256)

    """,
        StructureException,
    ),
    (
        """
@internal
def test(a : uint256):
    pass


@external
def burn(_value: uint256):
    self.test(msg.sender._value)
    """,
        UnknownAttribute,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_functions_call_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo(x: int128) -> uint256:
    return convert(x, uint256)
    """,
    """
from ethereum.ercs import IERC20

interface Factory:
    def getExchange(token_addr: address) -> address: view

token: IERC20
factory: Factory

@external
def setup(token_addr: address):
    self.token = IERC20(token_addr)
    assert staticcall self.factory.getExchange(self.token.address) == self
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_functions_call_success(good_code):
    assert compiler.compile_code(good_code) is not None

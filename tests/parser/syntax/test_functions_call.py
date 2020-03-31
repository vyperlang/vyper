import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    StructureException,
    UndeclaredDefinition,
    UnknownAttribute,
)

fail_list = [
    ("""
@public
def foo() -> uint256:
    doesnotexist(2, uint256)
    return convert(2, uint256)
    """, UndeclaredDefinition),
    ("""
@public
def foo() -> uint256:
    convert(2, uint256)
    return convert(2, uint256)

    """, StructureException),
    ("""
@private
def test(a : uint256):
    pass


@public
def burn(_value: uint256):
    self.test(msg.sender._value)
    """, UnknownAttribute),
]


@pytest.mark.parametrize('bad_code,exc', fail_list)
def test_functions_call_fail(bad_code, exc):

    with raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo() -> uint256:
    return convert(2, uint256)
    """,
    """
from vyper.interfaces import ERC20

contract Factory:
    def getExchange(token_addr: address) -> address: constant

token: ERC20
factory: Factory

@public
def setup(token_addr: address):
    self.token = ERC20(token_addr)
    assert self.factory.getExchange(self.token.address) == self
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_functions_call_success(good_code):
    assert compiler.compile_code(good_code) is not None

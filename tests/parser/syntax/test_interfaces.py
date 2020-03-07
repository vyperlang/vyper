import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    InvalidType,
    StructureException,
    TypeMismatch,
    VariableDeclarationException,
)

fail_list = [
    ("""
from vyper.interfaces import ERC20
a: public(ERC20)
@public
def test():
    b: uint256 = self.a
    """, TypeMismatch),
    ("""
from vyper.interfaces import ERC20
aba: public(ERC20)
@public
def test():
    self.aba = ERC20
    """, VariableDeclarationException),
    ("""
from vyper.interfaces import ERC20

a: address(ERC20) # invalid syntax now.
    """, StructureException),
    ("""
from vyper.interfaces import ERC20

@public
def test():
    a: address(ERC20) = ZERO_ADDRESS
    """, InvalidType),
    ("""
a: address

@public
def test():  # may not call normal address
    assert self.a.random()
    """, StructureException),
    ("""
from vyper.interfaces import ERC20
@public
def test(a: address):
    my_address: address = ERC20()
    """, TypeMismatch)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_interfaces_fail(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
from vyper.interfaces import ERC20
b: ERC20
@public
def test(input: address):
    assert self.b.totalSupply() == ERC20(input).totalSupply()
    """,
    """
from vyper.interfaces import ERC20

contract Factory:
   def getExchange(token_addr: address) -> address: constant

factory: Factory
token: ERC20

@public
def test():
    assert self.factory.getExchange(self.token) == self
    exchange: address = self.factory.getExchange(self.token)
    assert exchange == self.token
    assert self.token.totalSupply() > 0
    """,
    """
from vyper.interfaces import ERC20

a: public(ERC20)
    """,
    """
from vyper.interfaces import ERC20

a: public(ERC20)

@public
def test() -> address:
    return self.a
    """,
    """
from vyper.interfaces import ERC20

a: public(ERC20)
b: address

@public
def test():
    self.b = self.a
    """,
    """
from vyper.interfaces import ERC20

struct aStruct:
   my_address: address

a: public(ERC20)
b: aStruct

@public
def test() -> address:
    self.b.my_address = self.a
    return self.b.my_address
    """,
    """
from vyper.interfaces import ERC20
a: public(ERC20)
@public
def test():
    b: address = self.a
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_interfaces_success(good_code):
    assert compiler.compile_code(good_code) is not None


def test_imports_and_implements_within_interface():
    interface_code = """
from vyper.interfaces import ERC20
import foo.bar as Baz

implements: Baz

@public
def foobar():
    pass
"""

    code = """
import foo as Foo

implements: Foo

@public
def foobar():
    pass
"""

    assert compiler.compile_code(
        code,
        interface_codes={'Foo': {'type': "vyper", 'code': interface_code}}
    ) is not None

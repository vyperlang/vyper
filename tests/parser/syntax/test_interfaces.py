import pytest

from vyper import compiler
from vyper.exceptions import (
    ArgumentException,
    InvalidReference,
    StructureException,
    SyntaxException,
    TypeMismatch,
    UnknownAttribute,
)

fail_list = [
    (
        """
from vyper.interfaces import ERC20
a: public(ERC20)
@external
def test():
    b: uint256 = self.a
    """,
        TypeMismatch,
    ),
    (
        """
from vyper.interfaces import ERC20
aba: public(ERC20)
@external
def test():
    self.aba = ERC20
    """,
        InvalidReference,
    ),
    (
        """
from vyper.interfaces import ERC20

a: address(ERC20) # invalid syntax now.
    """,
        SyntaxException,
    ),
    (
        """
from vyper.interfaces import ERC20

@external
def test():
    a: address(ERC20) = ZERO_ADDRESS
    """,
        (StructureException, SyntaxException),
    ),
    (
        """
a: address

@external
def test():  # may not call normal address
    assert self.a.random()
    """,
        UnknownAttribute,
    ),
    (
        """
from vyper.interfaces import ERC20
@external
def test(a: address):
    my_address: address = ERC20()
    """,
        ArgumentException,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_interfaces_fail(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
from vyper.interfaces import ERC20
b: ERC20
@external
def test(input: address):
    assert self.b.totalSupply() == ERC20(input).totalSupply()
    """,
    """
from vyper.interfaces import ERC20

interface Factory:
   def getExchange(token_addr: address) -> address: view

factory: Factory
token: ERC20

@external
def test():
    assert self.factory.getExchange(self.token.address) == self
    exchange: address = self.factory.getExchange(self.token.address)
    assert exchange == self.token.address
    assert self.token.totalSupply() > 0
    """,
    """
interface Foo:
    def foo(): view

@external
def test() -> (bool, Foo):
    x: Foo = Foo(msg.sender)
    return True, x
    """
    """
from vyper.interfaces import ERC20

a: public(ERC20)
    """,
    """
from vyper.interfaces import ERC20

a: public(ERC20)

@external
def test() -> address:
    return self.a.address
    """,
    """
from vyper.interfaces import ERC20

a: public(ERC20)
b: address

@external
def test():
    self.b = self.a.address
    """,
    """
from vyper.interfaces import ERC20

struct aStruct:
   my_address: address

a: public(ERC20)
b: aStruct

@external
def test() -> address:
    self.b.my_address = self.a.address
    return self.b.my_address
    """,
    """
from vyper.interfaces import ERC20
a: public(ERC20)
@external
def test():
    b: address = self.a.address
    """,
    """
interface MyInterface:
    def some_func(): nonpayable

my_interface: MyInterface[3]
idx: uint256

@external
def __init__():
    self.my_interface[self.idx] = MyInterface(ZERO_ADDRESS)
    """,
    """
interface MyInterface:
    def kick(): payable

kickers: HashMap[address, MyInterface]
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_interfaces_success(good_code):
    assert compiler.compile_code(good_code) is not None


def test_imports_and_implements_within_interface():
    interface_code = """
from vyper.interfaces import ERC20
import foo.bar as Baz

implements: Baz

@external
def foobar():
    pass
"""

    code = """
import foo as Foo

implements: Foo

@external
def foobar():
    pass
"""

    assert (
        compiler.compile_code(
            code, interface_codes={"Foo": {"type": "vyper", "code": interface_code}}
        )
        is not None
    )

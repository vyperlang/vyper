import pytest

from vyper import compiler
from vyper.exceptions import (
    ArgumentException,
    InterfaceViolation,
    InvalidReference,
    InvalidType,
    StructureException,
    SyntaxException,
    TypeMismatch,
    UnknownAttribute,
)

fail_list = [
    (
        """
from ethereum.ercs import ERC20
a: public(ERC20)
@external
def test():
    b: uint256 = self.a
    """,
        TypeMismatch,
    ),
    (
        """
from ethereum.ercs import ERC20
aba: public(ERC20)
@external
def test():
    self.aba = ERC20
    """,
        InvalidReference,
    ),
    (
        """
from ethereum.ercs import ERC20

a: address(ERC20) # invalid syntax now.
    """,
        SyntaxException,
    ),
    (
        """
from ethereum.ercs import ERC20

@external
def test():
    a: address(ERC20) = empty(address)
    """,
        InvalidType,
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
from ethereum.ercs import ERC20
@external
def test(a: address):
    my_address: address = ERC20()
    """,
        ArgumentException,
    ),
    (
        """
from ethereum.ercs import ERC20

implements: ERC20 = 1
    """,
        SyntaxException,
    ),
    (
        """
interface A:
    @external
    def foo(): nonpayable
    """,
        StructureException,
    ),
    (
        """
implements: self.x
    """,
        InvalidType,
    ),
    (
        """
implements: 123
    """,
        StructureException,
    ),
    (
        """
struct Foo:
    a: uint256

implements: Foo
    """,
        StructureException,
    ),
    (
        """
from ethereum.ercs import ERC20

interface A:
    def f(): view

@internal
def foo():
    a: ERC20 = A(empty(address))
    """,
        TypeMismatch,
    ),
    (
        """
interface A:
    def f(a: uint256): view

implements: A

@external
@nonpayable
def f(a: uint256): # visibility is nonpayable instead of view
    pass
    """,
        InterfaceViolation,
    ),
    (
        # `receiver` of `Transfer` event should be indexed
        """
from ethereum.ercs import ERC20

implements: ERC20

event Transfer:
    sender: indexed(address)
    receiver: address
    value: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

name: public(String[32])
symbol: public(String[32])
decimals: public(uint8)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)

@external
def transfer(_to : address, _value : uint256) -> bool:
    return True

@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    return True

@external
def approve(_spender : address, _value : uint256) -> bool:
    return True
    """,
        InterfaceViolation,
    ),
    (
        # `value` of `Transfer` event should not be indexed
        """
from ethereum.ercs import ERC20

implements: ERC20

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: indexed(uint256)

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

name: public(String[32])
symbol: public(String[32])
decimals: public(uint8)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)

@external
def transfer(_to : address, _value : uint256) -> bool:
    return True

@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    return True

@external
def approve(_spender : address, _value : uint256) -> bool:
    return True
    """,
        InterfaceViolation,
    ),
    (
        # `payable` decorator not implemented
        """
interface testI:
    def foo() -> uint256: payable

implements: testI

@external
def foo() -> uint256:
    return 0
    """,
        InterfaceViolation,
    ),
    (
        # decorators must be strictly identical
        """
interface Self:
    def protected_view_fn() -> String[100]: nonpayable

implements: Self

@external
@pure
def protected_view_fn() -> String[100]:
    return empty(String[100])
    """,
        InterfaceViolation,
    ),
    (
        # decorators must be strictly identical
        """
interface Self:
    def protected_view_fn() -> String[100]: view

implements: Self

@external
@pure
def protected_view_fn() -> String[100]:
    return empty(String[100])
    """,
        InterfaceViolation,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_interfaces_fail(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
from ethereum.ercs import ERC20
b: ERC20
@external
def test(input: address):
    assert self.b.totalSupply() == ERC20(input).totalSupply()
    """,
    """
from ethereum.ercs import ERC20

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
from ethereum.ercs import ERC20

a: public(ERC20)
    """,
    """
from ethereum.ercs import ERC20

a: public(ERC20)

@external
def test() -> address:
    return self.a.address
    """,
    """
from ethereum.ercs import ERC20

a: public(ERC20)
b: address

@external
def test():
    self.b = self.a.address
    """,
    """
from ethereum.ercs import ERC20

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
from ethereum.ercs import ERC20
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

@deploy
def __init__():
    self.my_interface[self.idx] = MyInterface(empty(address))
    """,
    """
interface MyInterface:
    def kick(): payable

kickers: HashMap[address, MyInterface]
    """,
    """
interface Foo:
    def append(a: uint256): payable

@external
def bar(x: address):
    a: Foo = Foo(x)
    a.append(1)
    """,
    """
interface Foo:
    def pop(): payable

@external
def foo(x: address):
    a: Foo = Foo(x)
    a.pop()
    """,
    """
interface ITestInterface:
    def foo() -> uint256: view

implements: ITestInterface

foo: public(constant(uint256)) = 1
    """,
    """
interface ITestInterface:
    def foo() -> uint256: view

implements: ITestInterface

foo: public(immutable(uint256))

@deploy
def __init__(x: uint256):
    foo = x
    """,
    # no namespace collision of interface after storage variable
    """
a: constant(uint256) = 1

interface A:
    def f(a: uint128): view
    """,
    # no namespace collision of storage variable after interface
    """
interface A:
    def f(a: uint256): view

a: constant(uint128) = 1
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_interfaces_success(good_code):
    assert compiler.compile_code(good_code) is not None


def test_imports_and_implements_within_interface(make_input_bundle):
    interface_code = """
@external
def foobar():
    ...
"""

    input_bundle = make_input_bundle({"foo.vyi": interface_code})

    code = """
import foo as Foo

implements: Foo

@external
def foobar():
    pass
"""

    assert compiler.compile_code(code, input_bundle=input_bundle) is not None

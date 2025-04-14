import pytest

from vyper import compiler
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    FunctionDeclarationException,
    InterfaceViolation,
    InvalidReference,
    InvalidType,
    ModuleNotFound,
    NamespaceCollision,
    PragmaException,
    StructureException,
    SyntaxException,
    TypeMismatch,
    UnknownAttribute,
)

fail_list = [
    (
        """
from ethereum.ercs import IERC20
a: public(IERC20)
@external
def test():
    b: uint256 = self.a
    """,
        TypeMismatch,
    ),
    (
        """
from ethereum.ercs import IERC20
aba: public(IERC20)
@external
def test():
    self.aba = IERC20
    """,
        InvalidReference,
    ),
    (
        """
from ethereum.ercs import IERC20

a: address(IERC20) # invalid syntax now.
    """,
        SyntaxException,
    ),
    (
        """
from ethereum.ercs import IERC20

@external
def test():
    a: address(IERC20) = empty(address)
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
from ethereum.ercs import IERC20
@external
def test(a: address):
    my_address: address = IERC20()
    """,
        ArgumentException,
    ),
    (
        """
from ethereum.ercs import IERC20

implements: IERC20 = 1
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
from ethereum.ercs import IERC20

interface A:
    def f(): view

@internal
def foo():
    a: IERC20 = A(empty(address))
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
        # exports two Transfer events
        """
from ethereum.ercs import IERC20

implements: IERC20

event Transfer:
    sender: indexed(address)
    receiver: address
    value: uint256

name: public(String[32])
symbol: public(String[32])
decimals: public(uint8)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)

@external
def transfer(_to : address, _value : uint256) -> bool:
    log Transfer(sender=msg.sender, receiver=_to, value=_value)
    return True

@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    log IERC20.Transfer(sender=_from, receiver=_to, value=_value)
    return True

@external
def approve(_spender : address, _value : uint256) -> bool:
    return True
    """,
        NamespaceCollision,
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
from ethereum.ercs import IERC20
b: IERC20
@external
def test(input: address):
    assert staticcall self.b.totalSupply() == staticcall IERC20(input).totalSupply()
    """,
    """
from ethereum.ercs import IERC20

interface Factory:
   def getExchange(token_addr: address) -> address: view

factory: Factory
token: IERC20

@external
def test():
    assert staticcall self.factory.getExchange(self.token.address) == self
    exchange: address = staticcall self.factory.getExchange(self.token.address)
    assert exchange == self.token.address
    assert staticcall self.token.totalSupply() > 0
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
from ethereum.ercs import IERC20

a: public(IERC20)
    """,
    """
from ethereum.ercs import IERC20

a: public(IERC20)

@external
def test() -> address:
    return self.a.address
    """,
    """
from ethereum.ercs import IERC20

a: public(IERC20)
b: address

@external
def test():
    self.b = self.a.address
    """,
    """
from ethereum.ercs import IERC20

struct aStruct:
   my_address: address

a: public(IERC20)
b: aStruct

@external
def test() -> address:
    self.b.my_address = self.a.address
    return self.b.my_address
    """,
    """
from ethereum.ercs import IERC20
a: public(IERC20)
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
    extcall a.append(1)
    """,
    """
interface Foo:
    def pop(): payable

@external
def foo(x: address):
    a: Foo = Foo(x)
    extcall a.pop()
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
    ibar_code = """
@external
def foobar():
    ...
"""
    ifoo_code = """
import bar

implements: bar

@external
def foobar():
    ...
"""

    input_bundle = make_input_bundle({"foo.vyi": ifoo_code, "bar.vyi": ibar_code})

    code = """
import foo as Foo

implements: Foo

@external
def foobar():
    pass
"""

    assert compiler.compile_code(code, input_bundle=input_bundle) is not None


def test_builtins_not_found(make_input_bundle):
    code = """
from vyper.interfaces import foobar
    """
    input_bundle = make_input_bundle({"code.vy": code})
    file_input = input_bundle.load_file("code.vy")
    with pytest.raises(ModuleNotFound) as e:
        compiler.compile_from_file_input(file_input, input_bundle=input_bundle)
    assert e.value._message == "vyper.interfaces.foobar"
    assert e.value._hint == "try renaming `vyper.interfaces` to `ethereum.ercs`"
    assert "code.vy:" in str(e.value)


@pytest.mark.parametrize("erc", ("ERC20", "ERC721", "ERC4626"))
def test_builtins_not_found2(erc, make_input_bundle):
    code = f"""
from ethereum.ercs import {erc}
    """
    input_bundle = make_input_bundle({"code.vy": code})
    file_input = input_bundle.load_file("code.vy")
    with pytest.raises(ModuleNotFound) as e:
        compiler.compile_from_file_input(file_input, input_bundle=input_bundle)
    assert e.value._message == f"ethereum.ercs.{erc}"
    assert e.value._hint == f"try renaming `{erc}` to `I{erc}`"
    assert "code.vy:" in str(e.value)


def test_interface_body_check(make_input_bundle):
    interface_code = """
@external
def foobar():
    return ...
"""

    input_bundle = make_input_bundle({"foo.vyi": interface_code})

    code = """
import foo as Foo

implements: Foo

@external
def foobar():
    pass
"""
    with pytest.raises(FunctionDeclarationException) as e:
        compiler.compile_code(code, input_bundle=input_bundle)

    assert e.value._message == "function body in an interface can only be `...`!"


def test_interface_body_check2(make_input_bundle):
    interface_code = """
@external
def foobar():
    ...

@external
def bar():
    ...

@external
def baz():
    ...
"""

    input_bundle = make_input_bundle({"foo.vyi": interface_code})

    code = """
import foo

implements: foo

@external
def foobar():
    pass

@external
def bar():
    pass

@external
def baz():
    pass
"""

    assert compiler.compile_code(code, input_bundle=input_bundle) is not None


invalid_visibility_code = [
    """
import foo as Foo
implements: Foo
@external
def foobar():
    pass
    """,
    """
import foo as Foo
implements: Foo
@internal
def foobar():
    pass
    """,
    """
import foo as Foo
implements: Foo
def foobar():
    pass
    """,
]


@pytest.mark.parametrize("code", invalid_visibility_code)
def test_internal_visibility_in_interface(make_input_bundle, code):
    interface_code = """
@internal
def foobar():
    ...
"""

    input_bundle = make_input_bundle({"foo.vyi": interface_code})

    with pytest.raises(FunctionDeclarationException) as e:
        compiler.compile_code(code, input_bundle=input_bundle)

    assert e.value._message == "Interface functions can only be marked as `@external`"


external_visibility_interface = [
    """
@external
def foobar():
    ...
def bar():
    ...
    """,
    """
def foobar():
    ...
@external
def bar():
    ...
    """,
]


@pytest.mark.parametrize("iface", external_visibility_interface)
def test_internal_implemenatation_of_external_interface(make_input_bundle, iface):
    input_bundle = make_input_bundle({"foo.vyi": iface})

    code = """
import foo as Foo
implements: Foo
@internal
def foobar():
    pass
def bar():
    pass
    """

    with pytest.raises(InterfaceViolation) as e:
        compiler.compile_code(code, input_bundle=input_bundle)

    assert e.value.message == "Contract does not implement all interface functions: bar(), foobar()"


def test_intrinsic_interfaces_different_types(make_input_bundle, get_contract):
    lib1 = """
@external
@view
def foo():
    pass
    """
    lib2 = """
@external
@view
def foo():
    pass
    """
    main = """
import lib1
import lib2

@external
def bar():
    assert lib1.__at__(self) == lib2.__at__(self)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(TypeMismatch):
        compiler.compile_code(main, input_bundle=input_bundle)


def test_intrinsic_interfaces_default_function(make_input_bundle, get_contract):
    lib1 = """
@external
@payable
def __default__():
    pass
    """
    main = """
import lib1

@external
def bar():
    extcall lib1.__at__(self).__default__()

    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(CallViolation):
        compiler.compile_code(main, input_bundle=input_bundle)


def test_intrinsic_interfaces_default_function_staticcall(make_input_bundle, get_contract):
    lib1 = """
@external
@view
def __default__() -> int128:
    return 43
    """
    main = """
import lib1

@external
def bar():
    foo:int128 = 0
    foo = staticcall lib1.__at__(self).__default__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(CallViolation):
        compiler.compile_code(main, input_bundle=input_bundle)


def test_nonreentrant_pragma_blocked_in_vyi(make_input_bundle):
    ifoo_code = """
# pragma nonreentrancy on

@external
def foobar():
    ...
"""

    input_bundle = make_input_bundle({"foo.vyi": ifoo_code})

    code = """
import foo as Foo
"""

    with pytest.raises(PragmaException):
        compiler.compile_code(code, input_bundle=input_bundle)

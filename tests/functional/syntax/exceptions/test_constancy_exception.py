import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import ImmutableViolation, StateAccessViolation


@pytest.mark.parametrize(
    "bad_code",
    [
        """
x: int128
@external
@view
def foo() -> int128:
    self.x = 5
    return 1""",
        """
@external
@view
def foo() -> int128:
    send(0x1234567890123456789012345678901234567890, 5)
    return 1""",
        """
@external
@view
def foo():
    selfdestruct(0x1234567890123456789012345678901234567890)""",
        """
x: int128
y: int128
@external
@view
def foo() -> int128:
    self.y = 9
    return 5""",
        """
@external
@view
def foo() -> int128:
    x: Bytes[4] = raw_call(
        0x1234567890123456789012345678901234567890, b"cow", max_outsize=4, gas=595757, value=9
    )
    return 5""",
        """
@external
@view
def foo() -> int128:
    x: address = create_minimal_proxy_to(0x1234567890123456789012345678901234567890, value=9)
    return 5""",
        # test constancy in range expressions
        """
glob: int128
@internal
def foo() -> int128:
    self.glob += 1
    return 5
@external
def bar():
    for i: int128 in range(self.foo(), bound=100):
        pass""",
        """
glob: int128
@internal
def foo() -> int128:
    self.glob += 1
    return 5
@external
def bar():
    for i: int128 in [1,2,3,4,self.foo()]:
        pass""",
        """
f:int128

@internal
def a (x:int128):
    self.f = 100

@view
@external
def b():
    self.a(10)""",
        # view cannot call payable internal
        """
@payable
@internal
def _foo() -> uint256:
    return msg.value

@view
@external
def bar() -> uint256:
    return self._foo()
""",
        """
interface A:
    def bar() -> uint16: view

@external
@pure
def test(to: address):
    a: A = A(to)
    x: uint16 = staticcall a.bar()
    """,
        """
interface A:
    def bar() -> uint16: nonpayable

@external
@view
def test(to: address):
    a: A = A(to)
    x: uint16 = extcall a.bar()
    """,
        """
interface A:
    def bar() -> uint16: nonpayable

@external
@view
def test(to: address):
    a: A = A(to)
    extcall a.bar()
    """,
        """
a:DynArray[uint16,3]
@deploy
def __init__():
    self.a = [1,2,3]
@view
@external
def bar()->DynArray[uint16,3]:
    x:uint16 = self.a.pop()
    return self.a # return [1,2]
    """,
        """
from ethereum.ercs import IERC20

token: IERC20

@external
@view
def topup(amount: uint256):
    assert extcall self.token.transferFrom(msg.sender, self, amount)
    """,
        """
@external
@view
def foo(_topic: bytes32):
    raw_log([_topic], b"")
    """,
        """
@external
@pure
def foo(_topic: bytes32):
    raw_log([_topic], b"")
    """,
    ],
)
def test_statefulness_violations(bad_code):
    with raises(StateAccessViolation):
        compiler.compile_code(bad_code)


@pytest.mark.parametrize(
    "bad_code",
    [
        """
@external
def foo(x: int128):
    x = 5
        """,
        """
@external
def test(a: uint256[4]):
    a[0] = 1
        """,
        """
@external
def test(a: uint256[4][4]):
    a[0][1] = 1
        """,
        """
struct Foo:
    a: DynArray[DynArray[uint256, 2], 2]

@external
def foo(f: Foo) -> Foo:
    f.a[1] = [0, 1]
    return f
        """,
    ],
)
def test_immutability_violations(bad_code):
    with raises(ImmutableViolation):
        compiler.compile_code(bad_code)


@pytest.mark.parametrize(
    "bad_code",
    [
        # assign to call return
        """
@internal
def g() -> uint256[3]:
    return [1, 2, 3]

@external
def f():
    self.g()[0] = 5
    """,
        # assign to constant, runtime index
        """
A: constant(uint256[3]) = [1, 2, 3]

@external
def f(i: uint256):
    j: uint256 = i
    A[j] = 5
    """,
        # assign to call return, runtime index
        """
@internal
def g() -> uint256[3]:
    return [1, 2, 3]

@external
def f(i: uint256):
    j: uint256 = i
    self.g()[j] = 5
    """,
        # assign to ternary
        """
a: uint256[3]
b: uint256[3]

@external
def f():
    (self.a if True else self.b)[0] = 1
    """,
        # assign to self
        """
@external
def f():
    self = 1
    """,
        # assign to self.balance
        """
@external
def f():
    self.balance = 100
    """,
        # assign to balance of a storage address
        """
addr: address

@external
def f():
    self.addr.balance = 1
    """,
        # assign to interface address
        """
interface IFoo:
    def foo() -> uint256: nonpayable

f: IFoo

@external
def g():
    self.f.address = empty(address)
    """,
        # assign to interface function
        """
interface IFoo:
    def foo() -> uint256: view

f: IFoo
g: IFoo

@external
def h():
    self.f.foo = self.g.foo
    """,
        # assign to internal function
        """
@internal
def a():
    pass

@internal
def b():
    pass

@external
def h():
    self.a = self.b
    """,
        # assign to member function
        """
arr: DynArray[uint256, 3]

@external
def h():
    self.arr.append = self.arr.append
    """,
        # assign to builtin function
        """
@external
def foo():
    convert = convert
    """,
    ],
)
def test_read_only_expression_violations(bad_code):
    with raises(ImmutableViolation) as e:
        compiler.compile_code(bad_code)

    assert e.value.message == "Read-only expression cannot be mutated."
    assert e.value.hint is None

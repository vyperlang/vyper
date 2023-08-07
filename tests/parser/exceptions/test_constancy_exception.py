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
    for i in range(self.foo(), self.foo() + 1):
        pass""",
        """
glob: int128
@internal
def foo() -> int128:
    self.glob += 1
    return 5
@external
def bar():
    for i in [1,2,3,4,self.foo()]:
        pass""",
        """
@external
def foo():
    x: int128 = 5
    for i in range(x):
        pass""",
        """
from vyper.interfaces import ERC20

token: ERC20

@external
@view
def topup(amount: uint256):
    assert self.token.transferFrom(msg.sender, self, amount)
        """,
        """
from vyper.interfaces import ERC20

token: ERC20

@external
@view
def topup(amount: uint256):
    x: bool = self.token.transferFrom(msg.sender, self, amount)
        """,
        """
from vyper.interfaces import ERC20

token: ERC20

@external
@view
def topup(amount: uint256):
    x: bool = False
    x = self.token.transferFrom(msg.sender, self, amount)
        """,
        """
from vyper.interfaces import ERC20

token: ERC20

@external
@view
def topup(amount: uint256) -> bool:
    return self.token.transferFrom(msg.sender, self, amount)
        """,
        """
a: DynArray[uint256, 3]

@external
@view
def foo():
    assert self.a.pop() > 123, "vyper"
        """,
        """
a: DynArray[uint256, 3]

@external
@view
def foo():
    x: uint256 = self.a.pop()
        """,
        """
a: DynArray[uint256, 3]

@external
@view
def foo():
    x: uint256 = 0
    x = self.a.pop()
        """,
        """
a: DynArray[uint256, 3]

@external
@view
def foo() -> uint256:
    return self.a.pop()
        """,
        """
@external
@view
def foo(x: address):
    assert convert(
        raw_call(
            x,
            b'',
            max_outsize=32,
            revert_on_failure=False
        ), uint256
    ) > 123, "vyper"
        """,
        """
@external
@view
def foo(a: address):
    x: address = create_minimal_proxy_to(a)
        """,
        """
@external
@view
def foo(a: address):
    x: address = empty(address)
    x = create_copy_of(a)
        """,
        """
@external
@view
def foo(a: address) -> address:
    return create_from_blueprint(a)
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

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
f:int128

@external
def a (x:int128):
    self.f = 100

@view
@external
def b():
    self.a(10)""",
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

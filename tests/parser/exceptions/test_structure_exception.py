import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    StructureException,
)

fail_list = [
    """
x[5] = 4
    """,
    """
@public
def foo(): pass

x: int128
    """,
    """
send(0x1234567890123456789012345678901234567890, 5)
    """,
    """
send(0x1234567890123456789012345678901234567890, 5)
    """,
    """
@public
def foo():
    x: int128 = 5
    for i in range(x):
        pass
    """,
    """
@public
def foo(x: int128):
    y: int128 = 7
    for i in range(x, x + y):
        pass
    """,
    """
x: int128
@public
@const
def foo() -> int128:
    pass
    """,
    """
x: int128
@public
@monkeydoodledoo
def foo() -> int128:
    pass
    """,
    """
x: int128
@public
@constant(123)
def foo() -> int128:
    pass
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = []
    """,
    """
@public
def foo():
    x: bytes32 = keccak256("moose", 3)
    """,
    """
@public
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, b"cow")
    """,
    """
@public
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
@public
def foo():
    x = create_forwarder_to(0x1234567890123456789012345678901234567890, b"cow")
    """,
    """
@public
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, b"cow", gas=111111, outsize=4, moose=9)
    """,
    """
@public
def foo():
    x = create_forwarder_to(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
x: public()
    """,
    """
@public
def foo():
    raw_log([], b"cow", "dog")
    """,
    """
@public
def foo():
    raw_log(b"cow", b"dog")
    """,
    """
@public
def foo():
    throe
    """,
    """
@public
def foo() -> int128(wei):
    x: address = 0x1234567890123456789012345678901234567890
    return x.balance()
    """,
    """
@public
def foo() -> int128:
    x: address = 0x1234567890123456789012345678901234567890
    return x.codesize()
    """,
    """
@public
def foo():
    x = concat(b"")
    """,
    """
@public
def foo():
    x = y = 3
    """,
    """
def foo() -> int128:
    q:int128 = 111
    return q
    """,
    """
q:int128 = 111
def foo() -> int128:
    return self.q
    """,
    """
b: map(int128, bytes32)
@public
def foo():
    del self.b[0], self.b[1]
    """,
    """
@public
def foo():
    b: int128
    del b
    """,
    """
contract F:
    def foo(): constant
struct S:
    x: int128
    """,
    """
g: int128
struct S:
    x: int128
    """,
    """
struct S:
    x: int128
s: S = S({x: int128}, 1)
    """,
    """
struct S:
    x: int128
s: S = S(1)
    """,
    """
struct S:
    x: int128
s: S = S()
    """,
    """
@public
@nonreentrant("B")
@nonreentrant("C")
def double_nonreentrant():
    pass
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with raises(StructureException):
        compiler.compile_code(bad_code)

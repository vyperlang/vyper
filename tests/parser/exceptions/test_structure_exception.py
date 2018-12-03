import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import StructureException


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
x: int128[5]
@public
def foo():
    self.x[2:4] = 3
    """,
    """
x: int128[5]
@public
def foo():
    z = self.x[2:4]
    """,
    """
@public
def foo():
    x: int128[5]
    z = x[2:4]
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
def foo():
    x: int128 = 5
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
    x: bytes32 = sha3("moose", 3)
    """,
    """
@public
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow")
    """,
    """
@public
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
@public
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, "cow")
    """,
    """
@public
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", gas=111111, outsize=4, moose=9)
    """,
    """
@public
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
x: public()
    """,
    """
@public
def foo():
    raw_log([], "cow", "dog")
    """,
    """
@public
def foo():
    raw_log("cow", "dog")
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
    x: address = ~self
    """,
    """
@public
def foo():
    x = concat("")
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
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with raises(StructureException):
        compiler.compile_code(bad_code)

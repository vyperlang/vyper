import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import StructureException


fail_list = [
    """
x[5] = 4
    """,
    """
@public
def foo(): pass

x: num
    """,
    """
send(0x1234567890123456789012345678901234567890, 5)
    """,
    """
send(0x1234567890123456789012345678901234567890, 5)
    """,
    """
x: num[5]
@public
def foo():
    self.x[2:4] = 3
    """,
    """
x: num[5]
@public
def foo():
    z = self.x[2:4]
    """,
    """
@public
def foo():
    x: num[5]
    z = x[2:4]
    """,
    """
@public
def foo():
    x: num = 5
    for i in range(x):
        pass
    """,
    """
@public
def foo():
    x: num = 5
    y: num = 7
    for i in range(x, x + y):
        pass
    """,
    """
x: num
@public
@const
def foo() -> num:
    pass
    """,
    """
x: num
@public
@monkeydoodledoo
def foo() -> num:
    pass
    """,
    """
x: num
@public
@constant(123)
def foo() -> num:
    pass
    """,
    """
foo: num[3]
@public
def foo():
    self.foo = []
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
def foo() -> num(wei):
    x: address = 0x1234567890123456789012345678901234567890
    return x.balance()
    """,
    """
@public
def foo() -> num:
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
def foo() -> num:
    q:num = 111
    return q
    """,
    """
q:num = 111
def foo() -> num:
    return self.q
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with raises(StructureException):
        compiler.compile(bad_code)

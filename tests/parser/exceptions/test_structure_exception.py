import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import StructureException


fail_list = [
    """
x[5] = 4
    """,
    """
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
def foo():
    self.x[2:4] = 3
    """,
    """
x: num[5]
def foo():
    z = self.x[2:4]
    """,
    """
def foo():
    x: num[5]
    z = x[2:4]
    """,
    """
def foo():
    x = 5
    for i in range(x):
        pass
    """,
    """
def foo():
    x = 5
    y = 7
    for i in range(x, x + y):
        pass
    """,
    """
x: num
@const
def foo() -> num:
    pass
    """,
    """
x: num
@monkeydoodledoo
def foo() -> num:
    pass
    """,
    """
x: num
@constant(123)
def foo() -> num:
    pass
    """,
    """
foo: num[3]
def foo():
    self.foo = []
    """,
    """
def foo():
    x = sha3("moose", 3)
    """,
    """
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow")
    """,
    """
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, "cow")
    """,
    """
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", gas=111111, outsize=4, moose=9)
    """,
    """
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, outsize=4)
    """,
    """
x: public()
    """,
    """
def foo():
    raw_log([], "cow", "dog")
    """,
    """
def foo():
    raw_log("cow", "dog")
    """,
    """
def foo():
    throe
    """,
    """
def foo() -> num(wei):
    x = 0x1234567890123456789012345678901234567890
    return x.balance()
    """,
    """
def foo() -> num:
    x = 0x1234567890123456789012345678901234567890
    return x.codesize()
    """,
    """
def foo():
    x = ~self
    """,
    """
def foo():
    x = concat("")
    """,
    """
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

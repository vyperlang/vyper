import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    ConstancyViolationException,
)

fail_list = [
    """
x: int128
@public
@constant
def foo() -> int128:
    self.x = 5
    return 1
    """,
    """
@public
@constant
def foo() -> int128:
    send(0x1234567890123456789012345678901234567890, 5)
    return 1
    """,
    """
@public
@constant
def foo() -> int128:
    selfdestruct(0x1234567890123456789012345678901234567890)
    """,
    """
x: timedelta
y: int128
@public
@constant
def foo() -> int128(sec):
    self.y = 9
    return 5
    """,
    """
@public
@constant
def foo() -> int128:
    x = raw_call(0x1234567890123456789012345678901234567890, b"cow", outsize=4, gas=595757, value=9)
    return 5
    """,
    """
@public
@constant
def foo() -> int128:
    x = create_forwarder_to(0x1234567890123456789012345678901234567890, value=9)
    return 5
    """,
    """
@public
def foo(x: int128):
    x = 5
    """,
    """
f:int128

@public
def a (x:int128)->int128:
    self.f = 100
    return x+5

@constant
@public
def b():
    p: int128 = self.a(10)
    """,
    """
f:int128

@public
def a (x:int128):
    self.f = 100

@constant
@public
def b():
    self.a(10)
    """,
    # test constancy in range expressions
    """
glob: int128
@public
def foo() -> int128:
    self.glob += 1
    return 5
@public
def bar():
    for i in range(self.foo(), self.foo() + 1):
        pass
    """,
    """
glob: int128
@public
def foo() -> int128:
    self.glob += 1
    return 5
@public
def bar():
    for i in range(self.foo()):
        pass
    """,
    """
glob: int128
@public
def foo() -> int128:
    self.glob += 1
    return 5
@public
def bar():
    for i in [1,2,3,4,self.foo()]:
        pass
    """,
    """
glob: int128
@public
def foo() -> int128:
    self.glob += 1
    return 5
@public
def bar():
    for i in range(self.foo(), 7):
        pass
    """,
    """
glob: int128
@public
def foo() -> int128:
    self.glob += 1
    return 5
@public
def bar():
    for i in range(3, self.foo()):
        pass
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_constancy_violation_exception(bad_code):
    with raises(ConstancyViolationException):
        compiler.compile_code(bad_code)

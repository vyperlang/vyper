import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    CallViolation,
    ConstancyViolation,
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
def foo():
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
    x: bytes[4] = raw_call(0x1234567890123456789012345678901234567890, b"cow", outsize=4, gas=595757, value=9)
    return 5
    """,
    """
@public
@constant
def foo() -> int128:
    x: address = create_forwarder_to(0x1234567890123456789012345678901234567890, value=9)
    return 5
    """,
    """
@public
def foo(x: int128):
    x = 5
    """,
    # test constancy in range expressions
    """
glob: int128
@private
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
@private
def foo() -> int128:
    self.glob += 1
    return 5
@public
def bar():
    for i in [1,2,3,4,self.foo()]:
        pass
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_constancy_violation_exception(bad_code):
    with raises(ConstancyViolation):
        compiler.compile_code(bad_code)


call_violation_list = [
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
]


@pytest.mark.parametrize('bad_code', call_violation_list)
def test_call_violation_exception(bad_code):
    with raises(CallViolation):
        compiler.compile_code(bad_code)

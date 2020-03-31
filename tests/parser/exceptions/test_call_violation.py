import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    CallViolation,
)

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
    """
@private
def foo():
    self.goo()

@public
def goo():
    self.foo()
    """,
]


@pytest.mark.parametrize('bad_code', call_violation_list)
def test_call_violation_exception(bad_code):
    with raises(CallViolation):
        compiler.compile_code(bad_code)

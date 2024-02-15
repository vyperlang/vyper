import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import CallViolation

call_violation_list = [
    """
f:int128

@external
def a (x:int128)->int128:
    self.f = 100
    return x+5

@view
@external
def b():
    p: int128 = self.a(10)
    """,
    """
@external
def goo():
    pass

@internal
def foo():
    self.goo()
    """,
    """
@deploy
def __init__():
    pass

@internal
def foo():
    self.__init__()
    """,
]


@pytest.mark.parametrize("bad_code", call_violation_list)
def test_call_violation_exception(bad_code):
    with raises(CallViolation):
        compiler.compile_code(bad_code)

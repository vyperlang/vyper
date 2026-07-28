import pytest

from vyper import compiler
from vyper.exceptions import InvalidReference

fail_list = [
    """
x: uint256

@external
def foo():
    send(0x1234567890123456789012345678901234567890, x)
    """,
    """
@external
def bar(x: int128) -> int128:
    return 3 * x

@external
def foo() -> int128:
    return bar(20)
    """,
    """
b: int128
@external
def foo():
    b = 7
    """,
    """
x: int128
@external
def foo():
    x = 5
    """,
    """
@external
def foo():
    int128 = 5
    """,
    """
a: public(constant(uint256)) = 1

@external
def foo():
    b: uint256 = self.a
    """,
    """
flag F:
    A
    B
x: bool
@external
def foo():
    self.x = (F == F)
    """,
    """
flag F:
    A
    B
x: bool
@external
def foo():
    self.x = (F != F)
    """,
    """
flag F:
    A
@external
def foo() -> uint256:
    return F + 1
    """,
    """
flag F:
    A
@external
def foo() -> F:
    return -F
    """,
    """
flag F:
    A
@external
def foo() -> bool:
    return F.A in [F]
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_reference_exception(bad_code):
    with pytest.raises(InvalidReference):
        compiler.compile_code(bad_code)

import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    StructureException,
    SyntaxException,
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
x: int128
@public
@constant(123)
def foo() -> int128:
    pass
    """,
    """
@public
def foo() -> int128:
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
@public
@nonreentrant("B")
@nonreentrant("C")
def double_nonreentrant():
    pass
    """,
    """
struct X:
    int128[5]: int128[7]
    """,
    """
b: map((int128, decimal), int128)
    """,
    """
x: int128(address)
    """,
    """
x: int128(2 ** 2)
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with pytest.raises(StructureException):
        compiler.compile_code(bad_code)


del_fail_list = [
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
]


@pytest.mark.parametrize('bad_code', del_fail_list)
def test_syntax_exception(bad_code):
    with pytest.raises(SyntaxException):
        compiler.compile_code(bad_code)

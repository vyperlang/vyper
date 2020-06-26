import pytest

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
x: int128
@public
@view(123)
def foo() -> int128:
    pass
    """,
    """
@public
def foo():
    throe
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
interface F:
    def foo(): view
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
b: HashMap[(int128, decimal), int128]
    """,
    """
@public
@nonreentrant("B")
@nonreentrant("C")
def double_nonreentrant():
    pass
    """,
    """
x: 5
    """,
    """
x: bytes <= wei
    """,
    """
x: string <= 33
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_type_exception(bad_code):
    with pytest.raises(StructureException):
        compiler.compile_code(bad_code)


del_fail_list = [
    """
x: int128(address)
    """,
    """
x: int128(2 ** 2)
    """,
    """
# invalid interface declaration (pass)
interface Bar:
    def set_lucky(arg1: int128): pass
    """,
    """
interface Bar:
# invalud interface declaration (assignment)
    def set_lucky(arg1: int128):
        arg1 = 1
        arg1 = 3
    """,
]

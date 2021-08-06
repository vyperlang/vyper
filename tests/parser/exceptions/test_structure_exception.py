import pytest

from vyper import compiler
from vyper.exceptions import StructureException

fail_list = [
    """
x[5] = 4
    """,
    """
send(0x1234567890123456789012345678901234567890, 5)
    """,
    """
send(0x1234567890123456789012345678901234567890, 5)
    """,
    """
x: int128
@external
@view(123)
def foo() -> int128:
    pass
    """,
    """
@external
def foo():
    throe
    """,
    """
@external
def foo() -> int128:
    x: address = 0x1234567890123456789012345678901234567890
    return x.balance()
    """,
    """
@external
def foo() -> int128:
    x: address = 0x1234567890123456789012345678901234567890
    return x.codesize()
    """,
    """
@external
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
@external
@nonreentrant("B")
@nonreentrant("C")
def double_nonreentrant():
    pass
    """,
    """
x: 5
    """,
    """
x: Bytes <= wei
    """,
    """
x: String <= 33
    """,
    """
CALLDATACOPY: int128
    """,
    """
@external
def foo():
    BALANCE: int128 = 45
    """,
    """
@external
def foo():
    true: int128 = 3
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

import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, StructureException

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
x: [bar, baz]
    """,
    """
x: [bar(int128), baz(baffle)]
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
struct X:
    int128[5]: int128[7]
    """,
    """
@external
def foo():
    true: int128 = 3
    """,
    """
n: HashMap[uint256, bool][3]
    """,
    """
a: constant(uint256) = 3
n: public(HashMap[uint256, uint256][a])
    """,
    """
a: immutable(uint256)
n: public(HashMap[uint256, bool][a])

@deploy
def __init__():
    a = 3
    """,
    """
n: HashMap[uint256, bool][3][3]
    """,
    """
m1: HashMap[uint8, uint8]
m2: HashMap[uint8, uint8]

@deploy
def __init__():
    self.m1 = self.m2
    """,
    """
m1: HashMap[uint8, uint8]

@deploy
def __init__():
    self.m1 = 234
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_type_exception(bad_code):
    with pytest.raises((StructureException, InvalidType)):
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
# invalid interface declaration (assignment)
    def set_lucky(arg1: int128):
        arg1 = 1
        arg1 = 3
    """,
]

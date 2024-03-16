import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo() -> int128[2]:
    return [3,block.timestamp]
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo() -> int128[2]:
    return [block.timestamp - block.timestamp, block.timestamp]
    """,
        TypeMismatch,
    ),
    """
@external
def foo() -> decimal:
    x: int128 = as_wei_value(5, "finney")
    y: int128 = block.timestamp + 50
    return x // y
    """,
    (
        """
@external
def foo():
    x: Bytes[10] = slice(b"cow", -1, block.timestamp)
    """,
        TypeMismatch,
    ),
    """
@external
def foo():
    x: int128 = 7
    y: int128 = min(x, block.timestamp)
    """,
    """
a: HashMap[uint256, int128]

@external
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
a: HashMap[int128, int128]

@external
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
struct X:
    x: uint256
struct Y:
    y: int128
@external
def add_record():
    a: X = X(x=block.timestamp)
    b: Y = Y(y=5)
    a.x = b.y
    """,
    """
@external
def foo(inp: Bytes[10]) -> Bytes[3]:
    return slice(inp, block.timestamp, 6)
    """,
    (
        """
@external
def foo() -> int128:
    return block.fail
""",
        Exception,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
a: HashMap[uint256, uint256]

@external
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
@external
def foo() -> uint256:
    x: uint256 = as_wei_value(5, "finney")
    y: uint256 = block.timestamp + 50 - block.timestamp
    return x // y
    """,
    """
@external
def foo() -> uint256[2]:
    return [block.timestamp + 86400, block.timestamp]
    """,
    """
@external
def foo():
    y: uint256 = min(block.timestamp + 30, block.timestamp + 50)
    """,
    """
struct X:
    x: uint256
@external
def add_record():
    a: X = X(x=block.timestamp)
    a.x = block.gaslimit
    a.x = block.basefee
    a.x = 5
    """,
    """
@external
def foo():
    x: uint256 = block.difficulty + 185
    if tx.origin == self:
        y: Bytes[35] = concat(block.prevhash, b"dog")
    """,
    """
@external
def foo():
    x: uint256 = block.prevrandao + 185
    if tx.origin == self:
        y: Bytes[35] = concat(block.prevhash, b"dog")
    """,
    """
@external
def foo() -> uint256:
    return tx.gasprice
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None

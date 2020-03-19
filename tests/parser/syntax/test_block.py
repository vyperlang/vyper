import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatch,
)

fail_list = [
    """
@public
def foo() -> int128[2]:
    return [3,block.timestamp]
    """,
    """
@public
def foo() -> int128[2]:
    return [block.timestamp - block.timestamp, block.timestamp]
    """,
    """
@public
def foo() -> decimal:
    x: int128 = as_wei_value(5, "finney")
    y: int128 = block.timestamp + 50
    return x / y
    """,
    """
@public
def foo():
    x: bytes[10] = slice("cow", 0, block.timestamp)
    """,
    """
@public
def foo():
    x: int128 = 7
    y: int128 = min(x, block.timestamp)
    """,
    """
a: map(uint256, int128)

@public
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
a: map(int128, int128)

@public
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
struct X:
    x: uint256
struct Y:
    y: int128
@public
def add_record():
    a: X = X({x: block.timestamp})
    b: Y = Y({y: 5})
    a.x = b.y
    """,
    """
@public
def foo(inp: bytes[10]) -> bytes[3]:
    return slice(inp, block.timestamp, 3)
    """,
    ("""
@public
def foo() -> int128:
    return block.fail
""", Exception)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
a: map(uint256, uint256)

@public
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
@public
def foo() -> uint256:
    x: uint256 = as_wei_value(5, "finney")
    y: uint256 = block.timestamp + 50 - block.timestamp
    return x / y
    """,
    """
@public
def foo() -> uint256[2]:
    return [block.timestamp + 86400, block.timestamp]
    """,
    """
@public
def foo():
    y: uint256 = min(block.timestamp + 30, block.timestamp + 50)
    """,
    """
struct X:
    x: uint256
@public
def add_record():
    a: X = X({x: block.timestamp})
    a.x = 5
    """,
    """
@public
def foo():
    x: uint256 = block.difficulty + 185
    if tx.origin == self:
        y: bytes[35] = concat(block.prevhash, b"dog")
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None

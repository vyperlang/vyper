import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def foo() -> int128:
    x: address = create_with_code_of(0x1234567890123456789012345678901234567890, value=block.timestamp)
    return 5
    """,
    """
@public
def foo() -> int128[2]:
    return [3,block.timestamp]
    """,
    """
@public
def foo() -> timedelta[2]:
    return [block.timestamp - block.timestamp, block.timestamp]
    """,
    """
@public
def foo() -> decimal(wei / sec):
    x: int128(wei) = as_wei_value(5, "finney")
    y: int128 = block.timestamp + 50
    return x / y
    """,
    """
@public
def foo():
    x: bytes[10] = slice("cow", start=0, len=block.timestamp)
    """,
    """
@public
def foo():
    x: int128 = 7
    y: int128 = min(x, block.timestamp)
    """,
    """
@public
def foo():
    y = min(block.timestamp + 30 - block.timestamp, block.timestamp)
    """,
    """
a: int128[timestamp]

@public
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
a: timestamp[int128]

@public
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
@public
def add_record():
    a: {x: timestamp} = {x: block.timestamp}
    b: {y: int128} = {y: 5}
    a.x = b.y
    """,
    """
@public
def foo(inp: bytes[10]) -> bytes[3]:
    return slice(inp, start=block.timestamp, len=3)
    """,
    """
@public
def foo() -> address:
    return as_unitless_number(block.coinbase)
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
            compiler.compile(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
a: timestamp[timestamp]


@public
def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
@public
def foo() -> uint256(wei / sec):
    x: uint256(wei) = as_wei_value(5, "finney")
    y: uint256(sec) = block.timestamp + 50 - block.timestamp
    return x / y
    """,
    """
@public
def foo() -> timestamp[2]:
    return [block.timestamp + 86400, block.timestamp]
    """,
    """
@public
def foo():
    y: timestamp = min(block.timestamp + 30, block.timestamp + 50)
    """,
    """
@public
def foo() -> uint256:
    return as_unitless_number(block.timestamp)
    """,
    """
@public
def add_record():
    a: {x: timestamp} = {x: block.timestamp}
    a.x = 5
    """,
    """
@public
def foo():
    x: uint256 = block.difficulty + 185
    if tx.origin == self:
        y: bytes[35] = concat(block.prevhash, "dog")
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None

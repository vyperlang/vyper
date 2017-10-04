import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def foo() -> num:
    x = create_with_code_of(0x1234567890123456789012345678901234567890, value=block.timestamp)
    return 5
    """,
    """
def foo() -> num[2]:
    return [3,block.timestamp]
    """,
    """
def foo() -> timedelta[2]:
    return [block.timestamp - block.timestamp, block.timestamp]
    """,
    """
def foo() -> num(wei / sec):
    x = as_wei_value(5, finney)
    y = block.timestamp + 50
    return x / y
    """,
    """
def foo():
    x = slice("cow", start=0, len=block.timestamp)
    """,
    """
def foo():
    x = 7
    y = min(x, block.timestamp)
    """,
    """
def foo():
    y = min(block.timestamp + 30 - block.timestamp, block.timestamp)
    """,
    """
a: num[timestamp]

def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
a: timestamp[num]

def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
def add_record():
    a = {x: block.timestamp}
    b = {y: 5}
    a.x = b.y
    """,
    """
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=block.timestamp, len=3)
    """,
    """
def foo() -> address:
    return as_unitless_number(block.coinbase)
    """,
    ("""
def foo() -> num:
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

def add_record():
    self.a[block.timestamp] = block.timestamp + 20
    """,
    """
def foo() -> num(wei / sec):
    x = as_wei_value(5, finney)
    y = block.timestamp + 50 - block.timestamp
    return x / y
    """,
    """
def foo() -> timestamp[2]:
    return [block.timestamp + 86400, block.timestamp]
    """,
    """
def foo():
    y = min(block.timestamp + 30, block.timestamp + 50)
    """,
    """
def foo() -> num:
    return as_unitless_number(block.timestamp)
    """,
    """
def add_record():
    a = {x: block.timestamp}
    a.x = 5
    """,
    """
def foo():
    x = block.difficulty + 185
    if tx.origin == self:
        y = concat(block.prevhash, "dog")
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None

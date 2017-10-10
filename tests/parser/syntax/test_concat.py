import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i2, i1, i1)
    """,
    """
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, 5)
    """,
    """
def sandwich(inp: bytes <= 100, inp2: bytes32) -> bytes <= 163:
    return concat(inp2, inp, inp2)
    """,
    """
y: bytes <= 10

def krazykonkat(z: bytes <= 10) -> bytes <= 24:
    x = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
    """,
    """
def cat_list(y: num) -> bytes <= 40:
    x = [y]
    return concat("test", y)
    """,
]

valid_list = [
    """
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i2)
    """,
    """
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i1, i1, i1)
    """,
    """
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i1)
    """,
    """
def sandwich(inp: bytes <= 100, inp2: bytes32) -> bytes <= 165:
    return concat(inp2, inp, inp2)
    """,
    """
y: bytes <= 10

def krazykonkat(z: bytes <= 10) -> bytes <= 25:
    x = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None

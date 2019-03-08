import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

fail_list = [
    """
@public
def cat(i1: bytes[10], i2: bytes[30]) -> bytes[40]:
    return concat(i1, i2, i1, i1)
    """,
    """
@public
def cat(i1: bytes[10], i2: bytes[30]) -> bytes[40]:
    return concat(i1, 5)
    """,
    """
@public
def sandwich(inp: bytes[100], inp2: bytes32) -> bytes[163]:
    return concat(inp2, inp, inp2)
    """,
    """
y: bytes[10]

@public
def krazykonkat(z: bytes[10]) -> bytes[24]:
    x: bytes[10] = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
    """,
    """
@public
def cat_list(y: int128) -> bytes[40]:
    x: int128[1] = [y]
    return concat("test", y)
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def cat(i1: bytes[10], i2: bytes[30]) -> bytes[40]:
    return concat(i1, i2)
    """,
    """
@public
def cat(i1: bytes[10], i2: bytes[30]) -> bytes[40]:
    return concat(i1, i1, i1, i1)
    """,
    """
@public
def cat(i1: bytes[10], i2: bytes[30]) -> bytes[40]:
    return concat(i1, i1)
    """,
    """
@public
def sandwich(inp: bytes[100], inp2: bytes32) -> bytes[165]:
    return concat(inp2, inp, inp2)
    """,
    """
y: bytes[10]

@public
def krazykonkat(z: bytes[10]) -> bytes[25]:
    x: bytes[3] = "cow"
    self.y = "horse"
    return concat(x, b" ", self.y, b" ", z)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None

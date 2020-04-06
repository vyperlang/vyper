import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    SyntaxException,
)

fail_list = [
    """
x: bytes[1:3]
    """,
    """
b: int128[int128: address]
    """,
    """
x: int128[5]
@public
def foo():
    self.x[2:4] = 3
    """,
    """
@public
def foo():
    x: address = ~self
    """,
    """
x: int128[5]
@public
def foo():
    z = self.x[2:4]
    """,
    """
@public
def foo():
    x: int128[5]
    z = x[2:4]
    """,
    """
Transfer: event({_&rom: indexed(address)})
    """,
    """
@public
def test() -> uint256:
    for i in range(0, 4):
      return 0
    else:
      return 1
    return 1
    """,
    """
@public
def foo():
    x = y = 3
    """,
    """
@public
def foo():
    x: address = 0x12345678901234567890123456789012345678901
    """,
    """
@public
def foo():
    x: address = 0x01234567890123456789012345678901234567890
    """,
    """
@public
def foo():
    x: string[100] = "these bytes are nо gооd because the o's are from the Russian alphabet"
    """,
    """
@public
def foo():
    x: string[100] = "这个傻老外不懂中文"
    """,
    """
@public
def foo():
    a: bytes[100] = b"ѓtest"
    """,
    """
@public
def foo():
    x: address = 0x01234567890123456789012345678901234567890
    """,
    """
@public
def foo():
    a: bytes32 = keccak256("ѓtest")
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_syntax_exception(bad_code):
    with raises(SyntaxException):
        compiler.compile_code(bad_code)

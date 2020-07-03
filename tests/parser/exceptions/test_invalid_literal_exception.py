import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidLiteral

fail_list = [
    """
b: decimal
@external
def foo():
    self.b = 7.5178246872145875217495129745982164981654986129846
    """,
    """
@external
def foo():
    x: uint256 = convert(-(-(-1)), uint256)
    """,
    """
@external
def foo(x: int128):
    y: int128 = 7
    for i in range(x, x + y):
        pass
    """,
    """
bar: int128[3]
@external
def foo():
    self.bar = []
    """,
    """
@external
def foo():
    x: address = create_forwarder_to(0x123456789012345678901234567890123456789)
    """,
    """
@external
def foo():
    x: Bytes[4] = raw_call(0x123456789012345678901234567890123456789, "cow", max_outsize=4)
    """,
    """
@external
def foo():
    x: String[100] = "these bytes are nо gооd because the o's are from the Russian alphabet"
    """,
    """
@external
def foo():
    x: String[100] = "这个傻老外不懂中文"
    """,
    """
@external
def foo():
    x: address = 0x12345678901234567890123456789012345678901
    """,
    """
@external
def foo():
    x: address = 0x01234567890123456789012345678901234567890
    """,
    """
@external
def foo():
    x: address = 0x123456789012345678901234567890123456789
    """,
    """
@external
def foo():
    a: Bytes[100] = "ѓtest"
    """,
    """
@external
def foo():
    a: bytes32 = keccak256("ѓtest")
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_literal_exception(bad_code):
    with raises(InvalidLiteral):
        compiler.compile_code(bad_code)

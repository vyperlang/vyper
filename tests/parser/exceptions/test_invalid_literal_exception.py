import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidLiteral

fail_list = [
    """
b: decimal
@public
def foo():
    self.b = 7.5178246872145875217495129745982164981654986129846
    """,
    """
@public
def foo():
    x = as_wei_value(0x05, "babbage")
    """,
    """
@public
def foo():
    send(0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae, 5)
    """,
    """
@public
def foo():
    x = convert(-(-(-1)), uint256)
    """,
    """
# Test decimal limit.
a:decimal

@public
def foo():
    self.a = 170141183460469231731687303715884105727.888
    """,
    """
@public
def overflow() -> uint256:
    return 2**256
    """,
    """
@public
def overflow2() -> uint256:
    a: uint256 = 2**256
    return a
    """,
    """
@public
def foo():
    x: address = create_forwarder_to(0x123456789012345678901234567890123456789)
    """,
    """
@public
def foo():
    x: bytes[4] = raw_call(0x123456789012345678901234567890123456789, "cow", max_outsize=4)
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
    x: address = 0x123456789012345678901234567890123456789
    """,
    """
@public
def foo():
    a: bytes[100] = "ѓtest"
    """,
    """
@public
def foo():
    a: bytes32 = keccak256("ѓtest")
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_literal_exception(bad_code):
    with raises(InvalidLiteral):
        compiler.compile_code(bad_code)

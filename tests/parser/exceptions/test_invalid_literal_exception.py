import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import InvalidLiteralException


fail_list = [
    """
def foo():
    x = 0x12345678901234567890123456789012345678901
    """,
    """
def foo():
    x = 0x01234567890123456789012345678901234567890
    """,
    """
def foo():
    x = 0x123456789012345678901234567890123456789
    """,
    """
def foo():
    x = -170141183460469231731687303715884105728
    """,
    """
def foo():
    x = -170141183460469231731687303715884105728.
    """,
    """
b: decimal
def foo():
    self.b = 7.5178246872145875217495129745982164981654986129846
    """,
    """
def foo():
    x = "these bytes are nо gооd because the o's are from the Russian alphabet"
    """,
    """
def foo():
    x = "这个傻老外不懂中文"
    """,
    """
def foo():
    x = raw_call(0x123456789012345678901234567890123456789, "cow", outsize=4)
    """,
    """
def foo():
    x = create_with_code_of(0x123456789012345678901234567890123456789)
    """,
    """
def foo():
    x = as_wei_value(5.1824, ada)
    """,
    """
def foo():
    x = as_wei_value(0x05, ada)
    """,
    """
def foo():
    x = as_wei_value(5, vader)
    """,
    """
def foo():
    send(0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae, 5)
    """,
    """
def foo():
    x = as_num256(821649876217461872458712528745872158745214187264875632587324658732648753245328764872135671285218762145)
    """,
    """
def foo():
    x = as_num256(-1)
    """,
    """
def foo():
    x = as_num256(3.1415)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_literal_exception(bad_code):
    with raises(InvalidLiteralException):
        compiler.compile(bad_code)

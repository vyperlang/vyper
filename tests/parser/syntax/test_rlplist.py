import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]
""",
"""
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[2]
""",
"""
def foo() -> bytes <= 500:
    x = RLPList('\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return x[1]
"""
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_type_mismatch_exception(bad_code):
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
def foo() -> bytes <= 500:
    x = RLPList('\xe0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return x[1]
    """,
    """
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[0]
    """,
    """
def foo() -> bytes32:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_rlp_success(good_code):
    assert compiler.compile(good_code) is not None

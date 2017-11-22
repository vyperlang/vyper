import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def foo():
    y = min(7, 0x1234567890123456789012345678901234567890)
    """,
    """
@public
def foo():
    y = min(7, as_num256(3))
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)

import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [

]


@pytest.mark.parametrize('bad_code', fail_list)
def test_byte_string_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)


valid_list = [
    """
def foo() -> bytes <= 10:
    return "badminton"
    """,
    """
def foo():
    x = "¡très bien!"
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_byte_string_success(good_code):
    assert compiler.compile(good_code) is not None

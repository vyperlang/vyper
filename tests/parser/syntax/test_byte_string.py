import pytest

from viper import compiler


valid_list = [
    """
@public
def foo() -> bytes <= 10:
    return "badminton"
    """,
    """
@public
def foo():
    x: bytes <= 11 = "¡très bien!"
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_byte_string_success(good_code):
    assert compiler.compile(good_code) is not None

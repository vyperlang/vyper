import pytest

from vyper import compiler

valid_list = [
    """
@public
def foo() -> string[10]:
    return "badminton"
    """,
    """
@public
def foo():
    x: string[11] = "¡très bien!"
    """,
    """
@public
def test() -> string[100]:
    return "hello world!"
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_byte_string_success(good_code):
    assert compiler.compile_code(good_code) is not None

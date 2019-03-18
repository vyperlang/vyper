import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

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
def foo() -> bool:
    x: string[15] = "¡très bien!"
    y: string[15] = "test"
    return x != y
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_string_success(good_code):
    assert compiler.compile_code(good_code) is not None


fail_list = [
    """
@public
def foo() -> bool:
    x: string[15] = "¡très bien!"
    y: string[12] = "test"
    return x != y
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_string_fail(bad_code):

    with pytest.raises(TypeMismatchException):
        compiler.compile_code(bad_code)

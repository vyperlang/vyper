import pytest

from vyper import compiler

valid_list = [
    """
@external
def foo() -> string[10]:
    return "badminton"
    """,
    """
@external
def foo():
    x: string[11] = "¡très bien!"
    """,
    """
@external
def foo() -> bool:
    x: string[15] = "¡très bien!"
    y: string[15] = "test"
    return x != y
    """,
    """
@external
def foo() -> bool:
    x: string[15] = "¡très bien!"
    y: string[12] = "test"
    return x != y
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_string_success(good_code):
    assert compiler.compile_code(good_code) is not None

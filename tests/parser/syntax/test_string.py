import pytest

from vyper import compiler

valid_list = [
    """
@external
def foo() -> String[10]:
    return "badminton"
    """,
    """
@external
def foo():
    x: String[11] = "¡très bien!"
    """,
    """
@external
def foo() -> bool:
    x: String[15] = "¡très bien!"
    y: String[15] = "test"
    return x != y
    """,
    """
@external
def foo() -> bool:
    x: String[15] = "¡très bien!"
    y: String[12] = "test"
    return x != y
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_string_success(good_code):
    assert compiler.compile_code(good_code) is not None

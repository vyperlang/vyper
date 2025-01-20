import pytest

from vyper import compiler
from vyper.exceptions import InvalidLiteral, StructureException

valid_list = [
    """
@external
def foo() -> String[10]:
    return "badminton"
    """,
    """
@external
def foo() -> bool:
    x: String[15] = "tres bien!"
    y: String[15] = "test"
    return x != y
    """,
    """
@external
def test() -> String[100]:
    return "hello world!"
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_string_success(good_code):
    assert compiler.compile_code(good_code) is not None


invalid_list = [
    (
        """
@external
def foo():
    # invalid type annotation - should be String[N]
    a: String = "abc"
    """,
        StructureException,
    ),
    (
        """
@external
@view
def compile_hash() -> bytes32:
    # GH issue #3088 - ord("è") == 232
    return keccak256("è")
    """,
        InvalidLiteral,
    ),
    (
        """
@external
def foo() -> bool:
    # ord("¡") == 161
    x: String[15] = "¡très bien!"
    y: String[12] = "test"
    return x != y
    """,
        InvalidLiteral,
    ),
]


@pytest.mark.parametrize("bad_code,exc", invalid_list)
def test_string_fail(get_contract, bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)

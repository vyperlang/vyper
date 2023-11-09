import pytest

from vyper import compiler
from vyper.exceptions import StructureException

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
    a: String = "abc"
    """,
        StructureException,
    )
]


@pytest.mark.parametrize("bad_code,exc", invalid_list)
def test_string_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)

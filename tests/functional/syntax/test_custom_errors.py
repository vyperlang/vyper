import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException


@pytest.mark.parametrize(
    "code,exc_text",
    [
        (
            """
error Unauthorized:
    pass

@external
def fail():
    Unauthorized()
            """,
            "To raise a custom error you must use `raise` or `assert`",
        ),
        (
            """
error Unauthorized:
    pass

@external
def fail():
    log Unauthorized()
            """,
            "To raise a custom error you must use `raise` or `assert`",
        ),
    ],
)
def test_custom_error_bad_usage_diagnostics(code, exc_text):
    with pytest.raises(StructureException, match=exc_text):
        compile_code(code)


def test_custom_error_with_address_member():
    code = """
error MyErr:
    address: uint256

@external
def foo():
    raise MyErr(address=1)
    """
    assert compile_code(code) is not None


def test_custom_error_with_address_name_and_type():
    code = """
error MyErr:
    address: address

@external
def foo():
    raise MyErr(address=msg.sender)
    """
    assert compile_code(code) is not None

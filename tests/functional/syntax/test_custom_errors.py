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

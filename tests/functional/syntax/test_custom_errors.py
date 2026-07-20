import warnings

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import InstantiationException, StructureException


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


def test_error_kwarg_hint():
    code = """
error MyError:
    a: uint256
    b: uint256

@external
def foo():
    raise MyError(1, 2)
    """

    with pytest.raises(InstantiationException) as excinfo:
        compile_code(code)

    assert excinfo.value.message == "Instantiating errors with positional arguments is not allowed"
    assert excinfo.value.hint == "use kwargs instead: `MyError(a=1, b=2)`"


def test_error_hint_from_assert():
    code = """
error MyError:
    a: uint256

@external
def foo(x: bool):
    assert x, MyError(1)
    """

    with pytest.raises(InstantiationException) as excinfo:
        compile_code(code)

    assert excinfo.value.message == "Instantiating errors with positional arguments is not allowed"
    assert excinfo.value.hint == "use kwargs instead: `MyError(a=1)`"


def test_no_arg_no_hint():
    code = """
error MyError:
    pass

@external
def foo():
    raise MyError()
    """

    with warnings.catch_warnings(record=True) as w:
        assert compile_code(code) is not None

    assert len(w) == 0


def test_kwargs_no_hint():
    code = """
error MyError:
    a: uint256

@external
def foo():
    raise MyError(a=1)
    """

    with warnings.catch_warnings(record=True) as w:
        assert compile_code(code) is not None

    assert len(w) == 0

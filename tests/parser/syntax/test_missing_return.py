import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException


fail_list = [
    """
@public
def foo() -> int128:
    pass
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_missing_return(bad_code):
    with raises(FunctionDeclarationException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo() -> int128:
    return 123
    """,
    """
@public
def foo() -> int128:
    if False:
        return 123
    """,  # For the time being this is valid code, even though it should not be.
]


@pytest.mark.parametrize('good_code', valid_list)
def test_return_success(good_code):
    assert compiler.compile(good_code) is not None

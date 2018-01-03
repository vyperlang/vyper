import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import StructureException


fail_list = [
    """
@public
def foo() -> num:
    pass
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_missing_return(bad_code):
    with raises(StructureException):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo() -> num:
    return 123
    """,
    """
@public
def foo() -> num:
    if false:
        return 123
    """,  # For the time being this is valid code, even though it should not be.
]


@pytest.mark.parametrize('good_code', valid_list)
def test_return_success(good_code):
    assert compiler.compile(good_code) is not None

import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException

fail_list = [
    """
@public
def ő1qwerty(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
"""
@public
def int128(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
"""
@public
def decimal(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
    """
@public
def wei(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
    """
@public
def false(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_varname_validity_fail(bad_code):
        with raises(FunctionDeclarationException):
            compiler.compile(bad_code)


valid_list = [
    """
@public
def func(i: int128) -> int128:
    variable : int128 = i
    return variable
    """,
    """
@public
def func_to_do_math(i: int128) -> int128:
    var_123 : int128 = i
    return var_123
    """,
    """
@public
def first1(i: int128) -> int128:
    _var123 : int128 = i
    return _var123
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_varname_validity_success(good_code):
        assert compiler.compile(good_code) is not None

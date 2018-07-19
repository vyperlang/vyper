import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import EventDeclarationException

fail_list = [
    """
Âssign: event({variable: int128})

@public
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log.Âssign(temp_var)
    return temp_var
    """,
    """
int128: event({variable: int128})

@public
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log.int128(temp_var)
    return temp_var
    """,
    """
decimal: event({variable: int128})

@public
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log.decimal(temp_var)
    return temp_var
    """,
    """
wei: event({variable: int128})

@public
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log.wei(temp_var)
    return temp_var
    """,
"""
false: event({variable: int128})

@public
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log.false(temp_var)
    return temp_var
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_varname_validity_fail(bad_code):
        with raises(EventDeclarationException):
            compiler.compile(bad_code)


valid_list = [
    """
Assigned: event({variable: int128})

@public
def foo(i: int128) -> int128:
    variable : int128 = i
    log.Assigned(variable)
    return variable
    """,
    """
_Assign: event({variable: int128})

@public
def foo(i: int128) -> int128:
    variable : int128 = i
    log._Assign(variable)
    return variable
    """,
    """
Assigned1: event({variable: int128})

@public
def foo(i: int128) -> int128:
    variable : int128 = i
    log.Assigned1(variable)
    return variable
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_varname_validity_success(good_code):
        assert compiler.compile(good_code) is not None

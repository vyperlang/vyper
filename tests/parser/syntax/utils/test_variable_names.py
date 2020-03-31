import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    NamespaceCollision,
    VariableDeclarationException,
)

fail_list = [  # noqa: E122
    """
@public
def foo(i: int128) -> int128:
    varő : int128 = i
    return varő
    """,
    """
@public
def foo(i: int128) -> int128:
    wei : int128 = i
    return wei
    """,
    """
@public
def foo(i: int128) -> int128:
    false : int128 = i
    return false
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_varname_validity_fail(bad_code):
    with raises(VariableDeclarationException):
        compiler.compile_code(bad_code)


collision_fail_list = [
    """
@public
def foo(i: int128) -> int128:
    int128 : int128 = i
    return int128
    """,
    """
@public
def foo(i: int128) -> int128:
    decimal : int128 = i
    return decimal
    """
]


@pytest.mark.parametrize('bad_code', collision_fail_list)
def test_varname_collision_fail(bad_code):
    with raises(NamespaceCollision):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo(i: int128) -> int128:
    variable : int128 = i
    return variable
    """,
    """
@public
def foo(i: int128) -> int128:
    var_123 : int128 = i
    return var_123
    """,
    """
@public
def foo(i: int128) -> int128:
    _var123 : int128 = i
    return _var123
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_varname_validity_success(good_code):
    assert compiler.compile_code(good_code) is not None

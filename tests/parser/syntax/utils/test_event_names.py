import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidType, NamespaceCollision, StructureException, SyntaxException

fail_list = [  # noqa: E122
    (
        """
event Âssign:
    variable: int128

@external
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log Âssign(temp_var)
    return temp_var
    """,
        StructureException,
    ),
    (
        """
event int128:
    variable: int128

@external
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log int128(temp_var)
    return temp_var
    """,
        NamespaceCollision,
    ),
    (
        """
event decimal:
    variable: int128

@external
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log decimal(temp_var)
    return temp_var
    """,
        NamespaceCollision,
    ),
    (
        """
event wei:
    variable: int128

@external
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log wei(temp_var)
    return temp_var
    """,
        StructureException,
    ),
    (
        """
event false:
    variable: int128

@external
def foo(i: int128) -> int128:
    temp_var : int128 = i
    log false(temp_var)
    return temp_var
    """,
        StructureException,
    ),
    (
        """
Transfer: eve.t({_from: indexed(address)})
    """,
        SyntaxException,
    ),
    (
        """
event Transfer:
    _from: i.dexed(address)
    _to: indexed(address)
    lue: uint256
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_varname_validity_fail(bad_code, exc):
    with raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
event Assigned:
    variable: int128

@external
def foo(i: int128) -> int128:
    variable : int128 = i
    log Assigned(variable)
    return variable
    """,
    """
event _Assign:
    variable: int128

@external
def foo(i: int128) -> int128:
    variable : int128 = i
    log _Assign(variable)
    return variable
    """,
    """
event Assigned1:
    variable: int128

@external
def foo(i: int128) -> int128:
    variable : int128 = i
    log Assigned1(variable)
    return variable
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_varname_validity_success(good_code):
    assert compiler.compile_code(good_code) is not None

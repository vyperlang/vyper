import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import NamespaceCollision, StructureException

fail_list = [
    """
@external
def ő1qwerty(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
    """
@external
def false(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
    """
@external
def wei(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var1
    """,
    # collision between getter and external function
    """
foo: public(uint256)

@external
def foo():
    pass
    """,
    # collision between getter and external function, reverse order
    """
@external
def foo():
    pass

foo: public(uint256)
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_varname_validity_fail(bad_code):
    with raises((StructureException, NamespaceCollision)):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def func(i: int128) -> int128:
    variable : int128 = i
    return variable
    """,
    """
@external
def func_to_do_math(i: int128) -> int128:
    var_123 : int128 = i
    return var_123
    """,
    """
@external
def first1(i: int128) -> int128:
    _var123 : int128 = i
    return _var123
    """,
    """
@external
def int128(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
    """
@external
def decimal(i: int128) -> int128:
    temp_var : int128 = i
    return temp_var
    """,
    """
@external
def floor():
    pass
    """,
    """
@internal
def append():
    pass

@external
def foo():
    self.append()
    """,
    # "method id" collisions between internal functions are allowed
    """
@internal
@view
def gfah():
    pass

@internal
@view
def eexo():
    pass
    """,
    # "method id" collisions between internal+external functions are allowed
    """
@internal
@view
def gfah():
    pass

@external
@view
def eexo():
    pass
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_varname_validity_success(good_code):
    assert compiler.compile_code(good_code) is not None

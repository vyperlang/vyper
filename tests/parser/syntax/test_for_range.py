import pytest

from pytest import (
    raises,
)
from vyper import (
    compiler,
)
from vyper.exceptions import (
    StructureException,
    TypeMismatchException,
)

valid_list = [
    """
@public
def foo():
    for i in range(10):
        pass
    """,
    """
@public
def foo():
    for i in range(10, 20):
        pass
    """,
    """
@public
def foo():
    x: int128 = 5
    for i in range(x, x + 10):
        pass
    """,
    """
@public
def test_for() -> int128:
    a: int128 = 0
    for i in range(MAX_INT128 - 3, MAX_INT128 - 2):
        a = i
    return a
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_range_success(good_code):
    assert compiler.compile_code(good_code) is not None


fail_list = [
    """
@public
def test_for() -> int128:
    a: int128 = 0
    # for i in range(MAX_INT128, MAX_INT128 + 2):
    for i in range(MAX_INT128, MAX_INT128):
        a = i
    return a
    """,
    ("""
@public
def test_for() -> int128:
    a: int128 = 0
    for i in range(1, MAX_INT128 + 2):
        a = i
    return a
    """, TypeMismatchException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_range(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(StructureException):
            compiler.compile_code(bad_code)

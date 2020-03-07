import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatch,
)

fail_list = [
    """
@public
def baa() -> decimal:
    return 2.0 ** 2
    """,
    """
@public
def foo(a: int128):
    b:int128(sec) = 0
    c:int128(sec**2) = 0
    c = b ** a
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_exponent_fail(bad_code):

    with raises(TypeMismatch):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo():
    a : int128(wei) = 0
    b : int128(wei**2) = 0
    a = 2
    b = a**2
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_exponent_success(good_code):
    assert compiler.compile_code(good_code) is not None

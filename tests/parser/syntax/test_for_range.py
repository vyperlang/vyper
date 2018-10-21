import pytest

from pytest import raises
from vyper import compiler

fail_list = [
    """
@public
def foo():
    for i in range(10, type=int32):
        pass
    """,
    """
@public
def foo():
    for i in range(10, type=random):
        pass
    """,
    """
@public
def foo():
    x: int128 = 5
    for i in range(10, type=uint256):
        y: int128 = i + x
    """,
    """
@public
def foo():
    for i in range(10, type=int128):
        y: int128 = floor(i)
    """
]

@pytest.mark.parametrize('bad_code', fail_list)
def test_type_fail(bad_code):

    with raises(Exception):
        compiler.compile(bad_code)


valid_list = [
    """
@public
def foo():
    for i in range(10, 20, type=int128):
        pass
    """,
    """
@public
def foo():
    x: uint256 = 5
    for i in range(x, x + 10, type=uint256):
        pass
    """,
    """
@public
def foo():
    x: uint256 = 5
    for i in range(10, type=uint256):
        y: uint256 = i + x
    """,
    """
@public
def foo():
    for i in range(10.0, type=decimal):
        y: int128 = floor(i)
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_type_success(good_code):
    assert compiler.compile(good_code) is not None


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
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_range_success(good_code):
    assert compiler.compile(good_code) is not None

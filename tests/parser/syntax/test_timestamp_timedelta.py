import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException


fail_list = [
    """
@public
def foo(x: timestamp) -> int128:
    return x
    """,
    """
@public
def foo(x: timestamp) -> timedelta:
    return x
    """,
    """
@public
def foo(x: timestamp, y: timedelta) -> bool:
    return y < x
    """,
    """
@public
def foo(x: timestamp, y: timedelta) -> timedelta:
    return x + y
    """,
    """
@public
def foo(x: timestamp, y: timestamp) -> timestamp:
    return x + y
    """,
    """
@public
def foo(x: timestamp) -> timestamp:
    return x * 2
    """,
    """
@public
def foo(x: timedelta, y: timedelta) -> timedelta:
    return x * y
    """,
    """
@public
def foo() -> timestamp:
    x: int128 = 30
    y: timestamp
    return x + y
    """,
    """
@public
def foo(x: timedelta, y: int128 (wei/sec)) -> int128:
    return x * y
    """,
    """
@public
def foo(x: timestamp, y: int128 (wei/sec)) -> wei_value:
    return x * y
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_timestamp_fail(bad_code):
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
@public
def foo(x: timestamp) -> timestamp:
    return x + 50
    """,
    """
@public
def foo() -> timestamp:
    return 720
    """,
    """
@public
def foo() -> timedelta:
    return 720
    """,
    """
@public
def foo(x: timestamp, y: timedelta) -> timestamp:
    return x + y
    """,

    """
@public
def foo(x: timestamp, y: timestamp) -> bool:
    return y > x
    """,
    """
@public
def foo(x: timedelta, y: timedelta) -> bool:
    return y == x
    """,
    """
@public
def foo(x: timestamp) -> timestamp:
    return x
    """,
    """
@public
@constant
def foo(x: timestamp) -> int128:
    return 5
    """,
    """
@public
@constant
def foo(x: timestamp) -> timestamp:
    return x
    """,
    """
@public
def foo(x: timestamp) -> timestamp:
    y: timestamp = x
    return y
    """,
    """
@public
def foo(x: timedelta) -> bool:
    return x > 50
    """,
    """
@public
def foo(x: timestamp) -> bool:
    return x > 12894712
    """,
    """
@public
def foo() -> timestamp:
    x: timestamp
    x = 30
    return x
    """,
    """
@public
def foo(x: timestamp, y: timestamp) -> timedelta:
    return x - y
    """,
    """
@public
def foo(x: timedelta, y: timedelta) -> timedelta:
    return x + y
    """,
    """
@public
def foo(x: timedelta) -> timedelta:
    return x * 2
    """,
    """
@public
def foo(x: timedelta, y: uint256(wei/sec)) -> wei_value:
    return x * y
    """,
    """
@public
def foo(x: uint256(sec, positional)) -> timestamp:
    return x
    """,
    """
x: timedelta
@public
def foo() -> uint256(sec):
    return self.x
    """,
    """
x: timedelta
y: uint256
@public
@constant
def foo() -> uint256(sec):
    return self.x
    """,
    """
x: timedelta
y: uint256
@public
def foo() -> uint256(sec):
    self.y = 9
    return 5
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_timestamp_success(good_code):
    assert compiler.compile(good_code) is not None

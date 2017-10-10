import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
def foo(x: timestamp) -> num:
    return x
    """,
    """
def foo(x: timestamp) -> timedelta:
    return x
    """,
    """
def foo(x: timestamp, y: timedelta) -> bool:
    return y < x
    """,
    """
def foo(x: timestamp, y: timedelta) -> timedelta:
    return x + y
    """,
    """
def foo(x: timestamp, y: timestamp) -> timestamp:
    return x + y
    """,
    """
def foo(x: timestamp) -> timestamp:
    return x * 2
    """,
    """
def foo(x: timedelta, y: timedelta) -> timedelta:
    return x * y
    """,
    """
def foo() -> timestamp:
    x = 30
    y: timestamp
    return x + y
    """,
    """
def foo(x: timedelta, y: num (wei/sec)) -> num:
    return x * y
    """,
    """
def foo(x: timestamp, y: num (wei/sec)) -> wei_value:
    return x * y
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_timestamp_fail(bad_code):
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
def foo(x: timestamp) -> timestamp:
    return x + 50
    """,
    """
def foo() -> timestamp:
    return 720
    """,
    """
def foo() -> timedelta:
    return 720
    """,
    """
def foo(x: timestamp, y: timedelta) -> timestamp:
    return x + y
    """,

    """
def foo(x: timestamp, y: timestamp) -> bool:
    return y > x
    """,
    """
def foo(x: timedelta, y: timedelta) -> bool:
    return y == x
    """,
    """
def foo(x: timestamp) -> timestamp:
    return x
    """,
    """
@constant
def foo(x: timestamp) -> num:
    return 5
    """,
    """
@constant
def foo(x: timestamp) -> timestamp:
    return x
    """,
    """
def foo(x: timestamp) -> timestamp:
    y = x
    return y
    """,
    """
def foo(x: timedelta) -> bool:
    return x > 50
    """,
    """
def foo(x: timestamp) -> bool:
    return x > 12894712
    """,
    """
def foo() -> timestamp:
    x: timestamp
    x = 30
    return x
    """,
    """
def foo(x: timestamp, y: timestamp) -> timedelta:
    return x - y
    """,
    """
def foo(x: timedelta, y: timedelta) -> timedelta:
    return x + y
    """,
    """
def foo(x: timedelta) -> timedelta:
    return x * 2
    """,
    """
def foo(x: timedelta, y: num (wei/sec)) -> wei_value:
    return x * y
    """,
    """
def foo(x: num(sec, positional)) -> timestamp:
    return x
    """,
    """
x: timedelta
def foo() -> num(sec):
    return self.x
    """,
    """
x: timedelta
y: num
@constant
def foo() -> num(sec):
    return self.x
    """,
    """
x: timedelta
y: num
def foo() -> num(sec):
    self.y = 9
    return 5
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_timestamp_success(good_code):
    assert compiler.compile(good_code) is not None

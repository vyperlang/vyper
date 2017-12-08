import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
Bar: __log__({_value: num[4]})
x: decimal[4]

@public
def foo():
    log.Bar(self.x)
    """,
    """
Bar: __log__({_value: num[4]})

@public
def foo():
    x: decimal[4]
    log.Bar(x)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_logging_fail(bad_code):

    with raises(TypeMismatchException):
        compiler.compile(bad_code)

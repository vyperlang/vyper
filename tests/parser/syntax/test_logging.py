import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

fail_list = [
    """
Bar: event({_value: int128[4]})
x: decimal[4]

@public
def foo():
    log.Bar(self.x)
    """,
    """
Bar: event({_value: int128[4]})

@public
def foo():
    x: decimal[4] = [0, 0, 0, 0]
    log.Bar(x)
    """,
    """
Sale: event({eth_sold: indexed(uint256(wei))})

@public
def logSale(amount: uint256):
   log.Sale(amount)
   """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_logging_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile_code(bad_code)

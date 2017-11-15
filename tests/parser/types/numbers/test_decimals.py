import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_decimal_test():
    decimal_test = """
def foo() -> num:
    return(floor(999.0))

def fop() -> num:
    return(floor(333.0 + 666.0))

def foq() -> num:
    return(floor(1332.1 - 333.1))

def bar() -> num:
    return(floor(27.0 * 37.0))

def baz() -> num:
    x = 27.0
    return(floor(x * 37.0))

def baffle() -> num:
    return(floor(27.0 * 37))

def mok() -> num:
    return(floor(999999.0 / 7.0 / 11.0 / 13.0))

def mol() -> num:
    return(floor(499.5 / 0.5))

def mom() -> num:
    return(floor(1498.5 / 1.5))

def mon() -> num:
    return(floor(2997.0 / 3))

def moo() -> num:
    return(floor(2997 / 3.0))

def foom() -> num:
    return(floor(1999.0 % 1000.0))

def foon() -> num:
    return(floor(1999.0 % 1000))

def foop() -> num:
    return(floor(1999 % 1000.0))
    """

    c = get_contract_with_gas_estimation(decimal_test)
    pre_txs = len(s.head_state.receipts)
    assert c.foo() == 999
    assert c.fop() == 999
    assert c.foq() == 999
    assert c.bar() == 999
    assert c.baz() == 999
    assert c.baffle() == 999
    assert c.mok() == 999
    assert c.mol() == 999
    assert c.mom() == 999
    assert c.mon() == 999
    assert c.moo() == 999
    assert c.foom() == 999
    assert c.foon() == 999
    assert c.foop() == 999
    post_txs = len(s.head_state.receipts)

    print('Passed basic addition, subtraction and multiplication tests')
    check_gas(decimal_test, num_txs=(post_txs - pre_txs))


def test_harder_decimal_test():
    harder_decimal_test = """
def phooey(inp: decimal) -> decimal:
    x = 10000.0
    for i in range(4):
        x = x * inp
    return x

def arg(inp: decimal) -> decimal:
    return inp

def garg() -> decimal:
    x = 4.5
    x *= 1.5
    return x

def harg() -> decimal:
    x = 4.5
    x *= 2
    return x

def iarg() -> wei_value:
    x = as_wei_value(7, wei)
    x *= 2
    return x
    """
    c = get_contract_with_gas_estimation(harder_decimal_test)
    assert c.phooey(1.2) == 20736.0
    assert c.phooey(-1.2) == 20736.0
    assert c.arg(-3.7) == -3.7
    assert c.arg(3.7) == 3.7
    assert c.garg() == 6.75
    assert c.harg() == 9.0
    assert c.iarg() == 14

    print('Passed fractional multiplication test')

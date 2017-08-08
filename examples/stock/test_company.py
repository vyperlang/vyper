import pytest

from ethereum.tools import tester as t
from ethereum import utils

from viper import compiler

@pytest.fixture
def tester():
    tester = t
    tester.s = t.Chain()
    tester.s.head_state.gas_limit = 10**9
    tester.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/stock/company.v.py').read()
    tester.company_address = t.a0
    # 100 shares @ 10^6 wei / share
    tester.total_shares = 100
    tester.share_price = 10**6
    tester.c = tester.s.contract(contract_code, language='viper', \
            args=[tester.company_address, tester.total_shares, tester.share_price])
    return tester

@pytest.fixture
def assert_tx_failed(tester, function_to_test, exception = t.TransactionFailed):
    initial_state = tester.s.snapshot()
    with pytest.raises(exception):
        function_to_test()
    tester.s.revert(initial_state)

def test_overbuy(tester):
    # If all the stock has been bought, you can't buy more
    test_shares = tester.total_shares / 2
    tester.c.buy_stock(sender=t.k1, value=int(test_shares * tester.share_price))
    tester.c.buy_stock(sender=t.k1, value=int(test_shares * tester.share_price))
    assert_tx_failed(tester, lambda: tester.c.buy_stock(sender=t.k1, value=tester.share_price))

def test_sell_without_stock(tester):
    # If you don't have any stock, you can't sell
    assert_tx_failed(tester, lambda: tester.c.sell_stock(1, sender=t.k1))
    tester.c.buy_stock(sender=t.k1, value=int(tester.total_shares * tester.share_price))
    tester.c.sell_stock(tester.total_shares, sender=t.k1)
    assert_tx_failed(tester, lambda: tester.c.sell_stock(1, sender=t.k1))

def test_oversell(tester):
    # You can't sell more than you own
    test_shares = tester.total_shares / 10
    tester.c.buy_stock(sender=t.k1, value=int(test_shares * tester.share_price))
    assert_tx_failed(tester, lambda: tester.c.sell_stock(tester.total_shares, sender=t.k1))

def test_valuation(tester):
    # Valuation is number of shares held times price
    assert tester.c.valuation() == 0
    tester.c.buy_stock(sender=t.k1, value=int(tester.total_shares * tester.share_price))
    assert tester.c.valuation() == (tester.total_shares * tester.share_price)

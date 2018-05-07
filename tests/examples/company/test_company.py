import pytest

from vyper import compiler


@pytest.fixture
def c(t, get_contract):
    return get_contractopen(
        open('examples/stock/company.v.py').read(),
        args=[company_address, 1000, 10**6]
    )


def test_overbuy(c, assert_tx_failed):
    # If all the stock has been bought, no one can buy more
    test_shares = int(c.total_shares() / 2)
    test_value = int(test_shares * c.price())
    c.buy_stock(sender=t.k1, value=test_value)
    c.buy_stock(sender=t.k1, value=test_value)
    assert c.stock_available() == 0
    assert c.get_holding(t.a1) == (test_shares * 2)
    one_stock = c.price()
    assert_tx_failed(lambda: c.buy_stock(sender=t.k1, value=one_stock))
    assert_tx_failed(lambda: c.buy_stock(sender=t.k2, value=one_stock))


def test_sell_without_stock(c, assert_tx_failed):
    # If you don't have any stock, you can't sell
    assert_tx_failed(lambda: c.sell_stock(1, sender=t.k1))
    assert_tx_failed(lambda: c.sell_stock(1, sender=t.k2))
    # Negative stock doesn't work either
    assert_tx_failed(lambda: c.sell_stock(-1, sender=t.k1))
    # But if you do, you can!
    test_shares = int(c.total_shares())
    test_value = int(test_shares * c.price())
    c.buy_stock(sender=t.k1, value=test_value)
    assert c.get_holding(t.a1) == test_shares
    c.sell_stock(test_shares, sender=t.k1)
    # But only until you run out
    assert_tx_failed(lambda: c.sell_stock(1, sender=t.k1))


def test_oversell(tester, assert_tx_failed):
    # You can't sell more than you own
    test_shares = int(c.total_shares())
    test_value = int(test_shares * c.price())
    c.buy_stock(sender=t.k1, value=test_value)
    assert_tx_failed(lambda: c.sell_stock(test_shares + 1, sender=t.k1))


def test_transfer(tester, assert_tx_failed):
    # If you don't have any stock, you can't transfer
    assert_tx_failed(lambda: c.transfer_stock(t.a2, 1, sender=t.k1))
    assert_tx_failed(lambda: c.transfer_stock(t.a1, 1, sender=t.k2))
    # You can't do negative transfers to gain stock
    assert_tx_failed(lambda: c.transfer_stock(t.a2, -1, sender=t.k1))
    # If you transfer, you don't have the stock anymore
    test_shares = int(c.total_shares())
    test_value = int(test_shares * c.price())
    c.buy_stock(sender=t.k1, value=test_value)
    assert c.get_holding(t.a1) == test_shares
    c.transfer_stock(t.a2, test_shares, sender=t.k1)
    assert_tx_failed(lambda: c.sell_stock(1, sender=t.k1))
    # But the other person does
    c.sell_stock(test_shares, sender=t.k2)


def test_paybill(tester, assert_tx_failed):
    # Only the company can authorize payments
    assert_tx_failed(lambda: c.pay_bill(t.a2, 1, sender=t.k1))
    # A company can only pay someone if it has the money
    assert_tx_failed(lambda: c.pay_bill(t.a2, 1, sender=t.k0))
    # If it has the money, it can pay someone
    test_value = int(c.total_shares() * c.price())
    c.buy_stock(sender=t.k1, value=test_value)
    c.pay_bill(t.a2, test_value, sender=t.k0)
    # Until it runs out of money
    assert_tx_failed(lambda: c.pay_bill(t.a3, 1, sender=t.k0))
    # Then no stockholders can sell their stock either
    assert_tx_failed(lambda: c.sell_stock(1, sender=t.k1))


def test_valuation(tester):
    # Valuation is number of shares held times price
    assert c.debt() == 0
    test_value = int(c.total_shares() * c.price())
    c.buy_stock(sender=t.k1, value=test_value)
    assert c.debt() == test_value


def test_logs(tester, get_logs):
    # Buy is logged
    c.buy_stock(sender=t.k1, value=7 * c.price())
    receipt = tester.s.head_state.receipts[-1]
    logs = get_logs(receipt, c)
    assert len(logs) == 1
    assert logs[0]["_event_type"] == b'Buy'
    assert logs[0]["_buy_order"] == 7

    # Sell is logged
    c.sell_stock(3, sender=t.k1)
    receipt = tester.s.head_state.receipts[-1]
    logs = get_logs(receipt, c)
    assert len(logs) == 1
    assert logs[0]["_event_type"] == b'Sell'
    assert logs[0]["_sell_order"] == 3

    # Transfer is logged
    c.transfer_stock(t.a2, 4, sender=t.k1)
    receipt = tester.s.head_state.receipts[-1]
    logs = get_logs(receipt, c)
    assert len(logs) == 1
    assert logs[0]["_event_type"] == b'Transfer'
    assert logs[0]["_value"] == 4

    # Pay is logged
    amount = 10**4
    c.pay_bill(t.a3, amount)
    receipt = tester.s.head_state.receipts[-1]
    logs = get_logs(receipt, c)
    assert len(logs) == 1
    assert logs[0]["_event_type"] == b'Pay'
    assert logs[0]["_amount"] == amount

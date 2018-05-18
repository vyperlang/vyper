import pytest


@pytest.fixture
def c(w3, get_contract):
    with open('examples/stock/company.v.py') as f:
        contract_code = f.read()
        contract = get_contract(contract_code, *[w3.eth.accounts[0], 1000, 10**6])
    return contract


def test_overbuy(w3, c, assert_tx_failed):
    # If all the stock has been bought, no one can buy more
    a1, a2 = w3.eth.accounts[1:3]
    test_shares = int(c.total_shares() / 2)
    test_value = int(test_shares * c.price())
    c.buy_stock(transact={"from": a1, "value": test_value})
    c.buy_stock(transact={"from": a1, "value": test_value})
    assert c.stock_available() == 0
    assert c.get_holding(a1) == (test_shares * 2)
    one_stock = c.price()
    assert_tx_failed(lambda: c.buy_stock(transact={'from': a1, 'value': one_stock}))
    assert_tx_failed(lambda: c.buy_stock(transact={'from': a2, 'value': one_stock}))


def test_sell_without_stock(w3, c, assert_tx_failed):
    a1, a2 = w3.eth.accounts[1:3]
    # If you don't have any stock, you can't sell
    assert_tx_failed(lambda: c.sell_stock(1, transact={'from': a1}))
    assert_tx_failed(lambda: c.sell_stock(1, transact={'from': a2}))
    # Negative stock doesn't work either
    assert_tx_failed(lambda: c.sell_stock(-1, transact={'from': a1}))
    # But if you do, you can!
    test_shares = int(c.total_shares())
    test_value = int(test_shares * c.price())
    c.buy_stock(transact={'from': a1, 'value': test_value})
    assert c.get_holding(a1) == test_shares
    c.sell_stock(test_shares, transact={'from': a1})
    # But only until you run out
    assert_tx_failed(lambda: c.sell_stock(1, transact={'from': a1}))


def test_oversell(w3, c, assert_tx_failed):
    a0, a1, a2 = w3.eth.accounts[:3]
    # You can't sell more than you own
    test_shares = int(c.total_shares())
    test_value = int(test_shares * c.price())
    c.buy_stock(transact={'from': a1, 'value': test_value})
    assert_tx_failed(lambda: c.sell_stock(test_shares + 1, transact={'from': a1}))


def test_transfer(w3, c, assert_tx_failed):
    # If you don't have any stock, you can't transfer
    a1, a2 = w3.eth.accounts[1:3]
    assert_tx_failed(lambda: c.transfer_stock(a2, 1, transact={'from': a1}))
    assert_tx_failed(lambda: c.transfer_stock(a1, 1, transact={'from': a2}))
    # You can't do negative transfers to gain stock
    assert_tx_failed(lambda: c.transfer_stock(a2, -1, transact={'from': a1}))
    # If you transfer, you don't have the stock anymore
    test_shares = int(c.total_shares())
    test_value = int(test_shares * c.price())
    c.buy_stock(transact={'from': a1, 'value': test_value})
    assert c.get_holding(a1) == test_shares
    c.transfer_stock(a2, test_shares, transact={'from': a1})
    assert_tx_failed(lambda: c.sell_stock(1, transact={'from': a1}))
    # But the other person does
    c.sell_stock(test_shares, transact={'from': a2})


def test_paybill(w3, c, assert_tx_failed):
    a0, a1, a2, a3 = w3.eth.accounts[:4]
    # Only the company can authorize payments
    assert_tx_failed(lambda: c.pay_bill(a2, 1, transact={'from': a1}))
    # A company can only pay someone if it has the money
    assert_tx_failed(lambda: c.pay_bill(a2, 1, transact={'from': a0}))
    # If it has the money, it can pay someone
    test_value = int(c.total_shares() * c.price())
    c.buy_stock(transact={'from': a1, 'value': test_value})
    c.pay_bill(a2, test_value, transact={'from': a0})
    # Until it runs out of money
    assert_tx_failed(lambda: c.pay_bill(a3, 1, transact={'from': a0}))
    # Then no stockholders can sell their stock either
    assert_tx_failed(lambda: c.sell_stock(1, transact={'from': a1}))


def test_valuation(w3, c):
    a1 = w3.eth.accounts[1]
    # Valuation is number of shares held times price
    assert c.debt() == 0
    test_value = int(c.total_shares() * c.price())
    c.buy_stock(transact={'from': a1, 'value': test_value})
    assert c.debt() == test_value


def test_logs(w3, c, get_logs):
    a0, a1, a2, a3 = w3.eth.accounts[:4]
    # Buy is logged
    logs = get_logs(c.buy_stock(transact={'from': a1, 'value': 7 * c.price()}), c, 'Buy')
    assert len(logs) == 1
    assert logs[0].args._buy_order == 7

    # Sell is logged
    logs = get_logs(c.sell_stock(3, transact={'from': a1}), c, 'Sell')
    assert len(logs) == 1
    assert logs[0].args._sell_order == 3

    # Transfer is logged
    logs = get_logs(c.transfer_stock(a2, 4, transact={'from': a1}), c, 'Transfer')
    assert len(logs) == 1
    assert logs[0].event == 'Transfer'
    assert logs[0].args._value == 4

    # Pay is logged
    amount = 10**4
    logs = get_logs(c.pay_bill(a3, amount, transact={}), c, 'Pay')
    assert len(logs) == 1
    assert logs[0].args._amount == amount

import pytest


@pytest.fixture
def c(env, get_contract):
    with open("examples/stock/company.vy") as f:
        contract_code = f.read()

    for acc in env.accounts[:5]:
        env.set_balance(acc, 10**20)

    return get_contract(contract_code, *[env.accounts[0], 1000, 10**6])


def test_overbuy(env, c, tx_failed):
    # If all the stock has been bought, no one can buy more
    a1, a2 = env.accounts[1:3]
    test_shares = int(c.totalShares() / 2)
    test_value = int(test_shares * c.price())
    c.buyStock(transact={"from": a1, "value": test_value})
    c.buyStock(transact={"from": a1, "value": test_value})
    assert c.stockAvailable() == 0
    assert c.getHolding(a1) == (test_shares * 2)
    one_stock = c.price()
    with tx_failed():
        c.buyStock(transact={"from": a1, "value": one_stock})
    with tx_failed():
        c.buyStock(transact={"from": a2, "value": one_stock})


def test_sell_without_stock(env, c, tx_failed):
    a1, a2 = env.accounts[1:3]
    # If you don't have any stock, you can't sell
    with tx_failed():
        c.sellStock(1, transact={"from": a1})
    with tx_failed():
        c.sellStock(1, transact={"from": a2})
    # But if you do, you can!
    test_shares = int(c.totalShares())
    test_value = int(test_shares * c.price())
    c.buyStock(transact={"from": a1, "value": test_value})
    assert c.getHolding(a1) == test_shares
    c.sellStock(test_shares, transact={"from": a1})
    # But only until you run out
    with tx_failed():
        c.sellStock(1, transact={"from": a1})


def test_oversell(env, c, tx_failed):
    a0, a1, a2 = env.accounts[:3]
    # You can't sell more than you own
    test_shares = int(c.totalShares())
    test_value = int(test_shares * c.price())
    c.buyStock(transact={"from": a1, "value": test_value})
    with tx_failed():
        c.sellStock(test_shares + 1, transact={"from": a1})


def test_transfer(env, c, tx_failed):
    # If you don't have any stock, you can't transfer
    a1, a2 = env.accounts[1:3]
    with tx_failed():
        c.transferStock(a2, 1, transact={"from": a1})
    with tx_failed():
        c.transferStock(a1, 1, transact={"from": a2})
    # If you transfer, you don't have the stock anymore
    test_shares = int(c.totalShares())
    test_value = int(test_shares * c.price())
    c.buyStock(transact={"from": a1, "value": test_value})
    assert c.getHolding(a1) == test_shares
    c.transferStock(a2, test_shares, transact={"from": a1})
    with tx_failed():
        c.sellStock(1, transact={"from": a1})
    # But the other person does
    c.sellStock(test_shares, transact={"from": a2})


def test_paybill(env, c, tx_failed):
    a0, a1, a2, a3 = env.accounts[:4]
    # Only the company can authorize payments
    with tx_failed():
        c.payBill(a2, 1, transact={"from": a1})
    # A company can only pay someone if it has the money
    with tx_failed():
        c.payBill(a2, 1, transact={"from": a0})
    # If it has the money, it can pay someone
    test_value = int(c.totalShares() * c.price())
    c.buyStock(transact={"from": a1, "value": test_value})
    c.payBill(a2, test_value, transact={"from": a0})
    # Until it runs out of money
    with tx_failed():
        c.payBill(a3, 1, transact={"from": a0})
    # Then no stockholders can sell their stock either
    with tx_failed():
        c.sellStock(1, transact={"from": a1})


def test_valuation(env, c):
    a1 = env.accounts[1]
    # Valuation is number of shares held times price
    assert c.debt() == 0
    test_value = int(c.totalShares() * c.price())
    c.buyStock(transact={"from": a1, "value": test_value})
    assert c.debt() == test_value


def test_logs(env, c, get_logs):
    a0, a1, a2, a3 = env.accounts[:4]
    # Buy is logged
    logs = get_logs(c.buyStock(transact={"from": a1, "value": 7 * c.price()}), c, "Buy")
    assert len(logs) == 1
    assert logs[0].args.buy_order == 7

    # Sell is logged
    logs = get_logs(c.sellStock(3, transact={"from": a1}), c, "Sell")
    assert len(logs) == 1
    assert logs[0].args.sell_order == 3

    # Transfer is logged
    logs = get_logs(c.transferStock(a2, 4, transact={"from": a1}), c, "Transfer")
    assert len(logs) == 1
    assert logs[0].event == "Transfer"
    assert logs[0].args.value == 4

    # Pay is logged
    amount = 10**4
    logs = get_logs(c.payBill(a3, amount, transact={}), c, "Pay")
    assert len(logs) == 1
    assert logs[0].args.amount == amount

import pytest


@pytest.fixture
def c(w3, get_contract):
    with open("examples/crowdfund.vy") as f:
        contract_code = f.read()
        contract = get_contract(contract_code, *[w3.eth.accounts[1], 50, 60])
    return contract


def test_crowdfund_example(c, w3):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c.participate(transact={"value": 5})

    assert c.timelimit() == 60
    assert c.deadline() - w3.eth.get_block("latest").timestamp == 59
    assert not w3.eth.get_block("latest").timestamp >= c.deadline()  # expired
    assert not w3.eth.get_balance(c.address) >= c.goal()  # not reached
    c.participate(transact={"value": 49})
    # assert c.reached()
    pre_bal = w3.eth.get_balance(a1)
    w3.testing.mine(100)
    assert not w3.eth.get_block("latest").number >= c.deadline()  # expired
    c.finalize(transact={})
    post_bal = w3.eth.get_balance(a1)
    assert post_bal - pre_bal == 54


def test_crowdfund_example2(c, w3, tx_failed):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c.participate(transact={"value": 1, "from": a3})
    c.participate(transact={"value": 2, "from": a4})
    c.participate(transact={"value": 3, "from": a5})
    c.participate(transact={"value": 4, "from": a6})

    assert c.timelimit() == 60
    w3.testing.mine(100)
    # assert c.expired()
    # assert not c.reached()
    pre_bals = [w3.eth.get_balance(x) for x in [a3, a4, a5, a6]]
    with tx_failed():
        c.refund(transact={"from": a0})
    c.refund(transact={"from": a3})
    with tx_failed():
        c.refund(transact={"from": a3})
    c.refund(transact={"from": a4})
    c.refund(transact={"from": a5})
    c.refund(transact={"from": a6})
    post_bals = [w3.eth.get_balance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

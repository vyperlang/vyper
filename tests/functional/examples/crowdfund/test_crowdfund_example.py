import pytest


@pytest.fixture
def c(revm_env, get_contract):
    with open("examples/crowdfund.vy") as f:
        contract_code = f.read()
    return get_contract(contract_code, *[revm_env.accounts[1], 50, 60])


def test_crowdfund_example(c, revm_env):
    a0, a1, a2, a3, a4, a5, a6 = revm_env.accounts[:7]
    c.participate(transact={"value": 5})
    revm_env.mine(1)

    assert c.timelimit() == 60
    assert c.deadline() - revm_env.get_block("latest").timestamp == 59
    assert revm_env.get_block("latest").timestamp < c.deadline()  # expired
    assert revm_env.get_balance(c.address) < c.goal()  # not reached
    c.participate(transact={"value": 49})
    # assert c.reached()
    pre_bal = revm_env.get_balance(a1)
    revm_env.mine(100)
    assert revm_env.get_block("latest").timestamp > c.deadline()  # expired
    c.finalize(transact={})
    post_bal = revm_env.get_balance(a1)
    assert post_bal - pre_bal == 54


def test_crowdfund_example2(c, revm_env, tx_failed):
    a0, a1, a2, a3, a4, a5, a6 = revm_env.accounts[:7]
    for i, a in enumerate(revm_env.accounts[3:7]):
        revm_env.set_balance(a, i + 1)

    c.participate(transact={"value": 1, "from": a3})
    c.participate(transact={"value": 2, "from": a4})
    c.participate(transact={"value": 3, "from": a5})
    c.participate(transact={"value": 4, "from": a6})

    assert c.timelimit() == 60
    revm_env.mine(100)
    # assert c.expired()
    # assert not c.reached()
    pre_bals = [revm_env.get_balance(x) for x in [a3, a4, a5, a6]]
    with tx_failed():
        c.refund(transact={"from": a0})
    c.refund(transact={"from": a3})
    with tx_failed():
        c.refund(transact={"from": a3})
    c.refund(transact={"from": a4})
    c.refund(transact={"from": a5})
    c.refund(transact={"from": a6})
    post_bals = [revm_env.get_balance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

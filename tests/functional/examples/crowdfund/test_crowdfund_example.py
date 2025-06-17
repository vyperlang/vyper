import pytest


@pytest.fixture(scope="module")
def c(env, get_contract):
    with open("examples/crowdfund.vy") as f:
        contract_code = f.read()
    return get_contract(contract_code, *[env.accounts[1], 50, 60])


def test_crowdfund_example(c, env):
    a0, a1, a2, a3, a4, a5, a6 = env.accounts[:7]
    env.set_balance(a0, 100)
    c.participate(value=5)
    env.timestamp += 1  # make sure auction has started

    assert c.timelimit() == 60
    assert c.deadline() - env.timestamp == 59
    assert env.timestamp < c.deadline()  # expired
    assert env.get_balance(c.address) < c.goal()  # not reached
    c.participate(value=49)
    # assert c.reached()
    pre_bal = env.get_balance(a1)
    env.timestamp += 100
    assert env.timestamp > c.deadline()  # expired
    c.finalize()
    post_bal = env.get_balance(a1)
    assert post_bal - pre_bal == 54


def test_crowdfund_example2(c, env, tx_failed):
    a0, a1, a2, a3, a4, a5, a6 = env.accounts[:7]
    for i, a in enumerate(env.accounts[3:7]):
        env.set_balance(a, i + 1)

    c.participate(value=1, sender=a3)
    c.participate(value=2, sender=a4)
    c.participate(value=3, sender=a5)
    c.participate(value=4, sender=a6)

    assert c.timelimit() == 60
    env.timestamp += 100
    # assert c.expired()
    # assert not c.reached()
    pre_bals = [env.get_balance(x) for x in [a3, a4, a5, a6]]
    with tx_failed():
        c.refund(sender=a0)
    c.refund(sender=a3)
    with tx_failed():
        c.refund(sender=a3)
    c.refund(sender=a4)
    c.refund(sender=a5)
    c.refund(sender=a6)
    post_bals = [env.get_balance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

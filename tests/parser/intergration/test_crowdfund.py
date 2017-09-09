import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_crowdfund():
    crowdfund = """

funders: {sender: address, value: wei_value}[num]
nextFunderIndex: num
beneficiary: address
deadline: timestamp
goal: wei_value
refundIndex: num
timelimit: timedelta

def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

@payable
def participate():
    assert block.timestamp < self.deadline
    nfi = self.nextFunderIndex
    self.funders[nfi].sender = msg.sender
    self.funders[nfi].value = msg.value
    self.nextFunderIndex = nfi + 1

@constant
def expired() -> bool:
    return block.timestamp >= self.deadline

@constant
def timestamp() -> timestamp:
    return block.timestamp

@constant
def deadline() -> timestamp:
    return self.deadline

@constant
def timelimit() -> timedelta:
    return self.timelimit

@constant
def reached() -> bool:
    return self.balance >= self.goal

def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

def refund():
    ind = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i].sender = 0x0000000000000000000000000000000000000000
        self.funders[i].value = 0
    self.refundIndex = ind + 30

    """

    c = get_contract(crowdfund, args=[t.a1, 50, 600])

    c.participate(value=5)
    assert c.timelimit() == 600
    assert c.deadline() - c.timestamp() == 600
    assert not c.expired()
    assert not c.reached()
    c.participate(value=49)
    assert c.reached()
    pre_bal = s.head_state.get_balance(t.a1)
    s.head_state.timestamp += 1000
    assert c.expired()
    c.finalize()
    post_bal = s.head_state.get_balance(t.a1)
    assert post_bal - pre_bal == 54

    c = get_contract(crowdfund, args=[t.a1, 50, 600])
    c.participate(value=1, sender=t.k3)
    c.participate(value=2, sender=t.k4)
    c.participate(value=3, sender=t.k5)
    c.participate(value=4, sender=t.k6)
    s.head_state.timestamp += 1000
    assert c.expired()
    assert not c.reached()
    pre_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
    c.refund()
    post_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

    print('Passed composite crowdfund test')


def test_crowdfund2():
    crowdfund2 = """

funders: {sender: address, value: wei_value}[num]
nextFunderIndex: num
beneficiary: address
deadline: timestamp
goal: wei_value
refundIndex: num
timelimit: timedelta

def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

@payable
def participate():
    assert block.timestamp < self.deadline
    nfi = self.nextFunderIndex
    self.funders[nfi] = {sender: msg.sender, value: msg.value}
    self.nextFunderIndex = nfi + 1

@constant
def expired() -> bool:
    return block.timestamp >= self.deadline

@constant
def timestamp() -> timestamp:
    return block.timestamp

@constant
def deadline() -> timestamp:
    return self.deadline

@constant
def timelimit() -> timedelta:
    return self.timelimit

@constant
def reached() -> bool:
    return self.balance >= self.goal

def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

def refund():
    ind = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = None
    self.refundIndex = ind + 30

    """

    c = get_contract(crowdfund2, args=[t.a1, 50, 600])

    c.participate(value=5)
    assert c.timelimit() == 600
    assert c.deadline() - c.timestamp() == 600
    assert not c.expired()
    assert not c.reached()
    c.participate(value=49)
    assert c.reached()
    pre_bal = s.head_state.get_balance(t.a1)
    s.head_state.timestamp += 1000
    assert c.expired()
    c.finalize()
    post_bal = s.head_state.get_balance(t.a1)
    assert post_bal - pre_bal == 54

    c = get_contract(crowdfund2, args=[t.a1, 50, 600])
    c.participate(value=1, sender=t.k3)
    c.participate(value=2, sender=t.k4)
    c.participate(value=3, sender=t.k5)
    c.participate(value=4, sender=t.k6)
    s.head_state.timestamp += 1000
    assert c.expired()
    assert not c.reached()
    pre_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
    c.refund()
    post_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

    print('Passed second composite crowdfund test')

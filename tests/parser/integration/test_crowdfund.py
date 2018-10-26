def test_crowdfund(w3, tester, get_contract_with_gas_estimation_for_constants):
    crowdfund = """

funders: {sender: address, value: wei_value}[int128]
nextFunderIndex: int128
beneficiary: address
deadline: public(timestamp)
goal: wei_value
refundIndex: int128
timelimit: public(timedelta)

@public
def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

@public
@payable
def participate():
    assert block.timestamp < self.deadline
    nfi: int128 = self.nextFunderIndex
    self.funders[nfi].sender = msg.sender
    self.funders[nfi].value = msg.value
    self.nextFunderIndex = nfi + 1

@public
@constant
def expired() -> bool:
    return block.timestamp >= self.deadline

@public
@constant
def block_timestamp() -> timestamp:
    return block.timestamp

@public
@constant
def reached() -> bool:
    return self.balance >= self.goal

@public
def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

@public
def refund():
    ind: int128 = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i].sender = 0x0000000000000000000000000000000000000000
        self.funders[i].value = 0
    self.refundIndex = ind + 30

    """
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c = get_contract_with_gas_estimation_for_constants(crowdfund, *[a1, 50, 60])
    c.participate(transact={'value': 5})
    assert c.timelimit() == 60
    assert c.deadline() - c.block_timestamp() == 59
    assert not c.expired()
    assert not c.reached()
    c.participate(transact={'value': 49})
    assert c.reached()
    pre_bal = w3.eth.getBalance(a1)
    w3.testing.mine(100)
    assert c.expired()
    c.finalize(transact={})
    post_bal = w3.eth.getBalance(a1)
    assert post_bal - pre_bal == 54

    c = get_contract_with_gas_estimation_for_constants(crowdfund, *[a1, 50, 60])
    c.participate(transact={'value': 1, 'from': a3})
    c.participate(transact={'value': 2, 'from': a4})
    c.participate(transact={'value': 3, 'from': a5})
    c.participate(transact={'value': 4, 'from': a6})
    w3.testing.mine(100)
    assert c.expired()
    assert not c.reached()
    pre_bals = [w3.eth.getBalance(x) for x in [a3, a4, a5, a6]]
    c.refund(transact={})
    post_bals = [w3.eth.getBalance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

    print('Passed composite crowdfund test')


def test_crowdfund2(w3, tester, get_contract_with_gas_estimation_for_constants):
    crowdfund2 = """

funders: {sender: address, value: wei_value}[int128]
nextFunderIndex: int128
beneficiary: address
deadline: public(timestamp)
goal: wei_value
refundIndex: int128
timelimit: public(timedelta)

@public
def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

@public
@payable
def participate():
    assert block.timestamp < self.deadline
    nfi: int128 = self.nextFunderIndex
    self.funders[nfi] = {sender: msg.sender, value: msg.value}
    self.nextFunderIndex = nfi + 1

@public
@constant
def expired() -> bool:
    return block.timestamp >= self.deadline

@public
@constant
def block_timestamp() -> timestamp:
    return block.timestamp

@public
@constant
def reached() -> bool:
    return self.balance >= self.goal

@public
def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

@public
def refund():
    ind: int128 = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = None
    self.refundIndex = ind + 30

    """
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c = get_contract_with_gas_estimation_for_constants(crowdfund2, *[a1, 50, 60])

    c.participate(transact={'value': 5})
    assert c.timelimit() == 60
    assert c.deadline() - c.block_timestamp() == 59
    assert not c.expired()
    assert not c.reached()
    c.participate(transact={'value': 49})
    assert c.reached()
    pre_bal = w3.eth.getBalance(a1)
    w3.testing.mine(100)
    assert c.expired()
    c.finalize(transact={})
    post_bal = w3.eth.getBalance(a1)
    assert post_bal - pre_bal == 54

    c = get_contract_with_gas_estimation_for_constants(crowdfund2, *[a1, 50, 60])
    c.participate(transact={'value': 1, 'from': a3})
    c.participate(transact={'value': 2, 'from': a4})
    c.participate(transact={'value': 3, 'from': a5})
    c.participate(transact={'value': 4, 'from': a6})
    w3.testing.mine(100)
    assert c.expired()
    assert not c.reached()
    pre_bals = [w3.eth.getBalance(x) for x in [a3, a4, a5, a6]]
    c.refund(transact={})
    post_bals = [w3.eth.getBalance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

    print('Passed second composite crowdfund test')

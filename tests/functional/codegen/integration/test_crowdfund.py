# TODO: check, this is probably redundant with examples/test_crowdfund.py
def test_crowdfund(w3, tester, get_contract_with_gas_estimation_for_constants):
    crowdfund = """

struct Funder:
    sender: address
    value: uint256
funders: HashMap[int128, Funder]
nextFunderIndex: int128
beneficiary: address
deadline: public(uint256)
goal: public(uint256)
refundIndex: int128
timelimit: public(uint256)

@deploy
def __init__(_beneficiary: address, _goal: uint256, _timelimit: uint256):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

@external
@payable
def participate():
    assert block.timestamp < self.deadline
    nfi: int128 = self.nextFunderIndex
    self.funders[nfi].sender = msg.sender
    self.funders[nfi].value = msg.value
    self.nextFunderIndex = nfi + 1

@external
@view
def expired() -> bool:
    return block.timestamp >= self.deadline

@external
@view
def block_timestamp() -> uint256:
    return block.timestamp

@external
@view
def reached() -> bool:
    return self.balance >= self.goal

@external
def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

@external
def refund():
    ind: int128 = self.refundIndex
    for i: int128 in range(ind, ind + 30, bound=30):
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
    start_timestamp = w3.eth.get_block(w3.eth.block_number).timestamp

    c.participate(transact={"value": 5})
    assert c.timelimit() == 60
    assert c.deadline() - start_timestamp == 60
    assert not c.expired()
    assert not c.reached()
    c.participate(transact={"value": 49})
    assert c.reached()
    pre_bal = w3.eth.get_balance(a1)
    w3.testing.mine(100)
    assert c.expired()
    c.finalize(transact={})
    post_bal = w3.eth.get_balance(a1)
    assert post_bal - pre_bal == 54

    c = get_contract_with_gas_estimation_for_constants(crowdfund, *[a1, 50, 60])
    c.participate(transact={"value": 1, "from": a3})
    c.participate(transact={"value": 2, "from": a4})
    c.participate(transact={"value": 3, "from": a5})
    c.participate(transact={"value": 4, "from": a6})
    w3.testing.mine(100)
    assert c.expired()
    assert not c.reached()
    pre_bals = [w3.eth.get_balance(x) for x in [a3, a4, a5, a6]]
    c.refund(transact={})
    post_bals = [w3.eth.get_balance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]


def test_crowdfund2(w3, tester, get_contract_with_gas_estimation_for_constants):
    crowdfund2 = """
struct Funder:
    sender: address
    value: uint256

funders: HashMap[int128, Funder]
nextFunderIndex: int128
beneficiary: address
deadline: public(uint256)
goal: uint256
refundIndex: int128
timelimit: public(uint256)

@deploy
def __init__(_beneficiary: address, _goal: uint256, _timelimit: uint256):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

@external
@payable
def participate():
    assert block.timestamp < self.deadline
    nfi: int128 = self.nextFunderIndex
    self.funders[nfi] = Funder(sender=msg.sender, value=msg.value)
    self.nextFunderIndex = nfi + 1

@external
@view
def expired() -> bool:
    return block.timestamp >= self.deadline

@external
@view
def block_timestamp() -> uint256:
    return block.timestamp

@external
@view
def reached() -> bool:
    return self.balance >= self.goal

@external
def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

@external
def refund():
    ind: int128 = self.refundIndex
    for i: int128 in range(ind, ind + 30, bound=30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = empty(Funder)
    self.refundIndex = ind + 30

    """
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c = get_contract_with_gas_estimation_for_constants(crowdfund2, *[a1, 50, 60])

    c.participate(transact={"value": 5})
    assert c.timelimit() == 60
    assert c.deadline() - c.block_timestamp() == 59
    assert not c.expired()
    assert not c.reached()
    c.participate(transact={"value": 49})
    assert c.reached()
    pre_bal = w3.eth.get_balance(a1)
    w3.testing.mine(100)
    assert c.expired()
    c.finalize(transact={})
    post_bal = w3.eth.get_balance(a1)
    assert post_bal - pre_bal == 54

    c = get_contract_with_gas_estimation_for_constants(crowdfund2, *[a1, 50, 60])
    c.participate(transact={"value": 1, "from": a3})
    c.participate(transact={"value": 2, "from": a4})
    c.participate(transact={"value": 3, "from": a5})
    c.participate(transact={"value": 4, "from": a6})
    w3.testing.mine(100)
    assert c.expired()
    assert not c.reached()
    pre_bals = [w3.eth.get_balance(x) for x in [a3, a4, a5, a6]]
    c.refund(transact={})
    post_bals = [w3.eth.get_balance(x) for x in [a3, a4, a5, a6]]
    assert [y - x for x, y in zip(pre_bals, post_bals)] == [1, 2, 3, 4]

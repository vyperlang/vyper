def test_arbitration_code(env, get_contract, tx_failed):
    arbitration_code = """
buyer: address
seller: address
arbitrator: address

@external
def setup(_seller: address, _arbitrator: address):
    if self.buyer == empty(address):
        self.buyer = msg.sender
        self.seller = _seller
        self.arbitrator = _arbitrator

@external
def finalize():
    assert msg.sender == self.buyer or msg.sender == self.arbitrator
    send(self.seller, self.balance)

@external
def refund():
    assert msg.sender == self.seller or msg.sender == self.arbitrator
    send(self.buyer, self.balance)

    """
    a0, a1, a2 = env.accounts[:3]
    env.set_balance(a0, 1)
    c = get_contract(arbitration_code, value=1)
    c.setup(a1, a2)
    with tx_failed():
        c.finalize(sender=a1)
    c.finalize()

    print("Passed escrow test")


def test_arbitration_code_with_init(env, tx_failed, get_contract):
    arbitration_code_with_init = """
buyer: address
seller: address
arbitrator: address

@deploy
@payable
def __init__(_seller: address, _arbitrator: address):
    if self.buyer == empty(address):
        self.buyer = msg.sender
        self.seller = _seller
        self.arbitrator = _arbitrator

@external
def finalize():
    assert msg.sender == self.buyer or msg.sender == self.arbitrator
    send(self.seller, self.balance)

@external
def refund():
    assert msg.sender == self.seller or msg.sender == self.arbitrator
    send(self.buyer, self.balance)
    """
    a0, a1, a2 = env.accounts[:3]
    env.set_balance(env.deployer, 1)
    c = get_contract(arbitration_code_with_init, *[a1, a2], value=1)
    with tx_failed():
        c.finalize(sender=a1)
    c.finalize(sender=a0)

    print("Passed escrow test with initializer")

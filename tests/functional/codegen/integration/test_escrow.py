# from ethereum.tools import tester


def test_arbitration_code(w3, get_contract_with_gas_estimation, tx_failed):
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
    a0, a1, a2 = w3.eth.accounts[:3]
    c = get_contract_with_gas_estimation(arbitration_code, value=1)
    c.setup(a1, a2, transact={})
    with tx_failed():
        c.finalize(transact={"from": a1})
    c.finalize(transact={})

    print("Passed escrow test")


def test_arbitration_code_with_init(w3, tx_failed, get_contract_with_gas_estimation):
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
    a0, a1, a2 = w3.eth.accounts[:3]
    c = get_contract_with_gas_estimation(arbitration_code_with_init, *[a1, a2], value=1)
    with tx_failed():
        c.finalize(transact={"from": a1})
    c.finalize(transact={"from": a0})

    print("Passed escrow test with initializer")

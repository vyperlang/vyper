from ethereum.tools import tester


def test_arbitration_code(t, get_contract_with_gas_estimation):
    arbitration_code = """
buyer: address
seller: address
arbitrator: address

@public
def setup(_seller: address, _arbitrator: address):
    if not self.buyer:
        self.buyer = msg.sender
        self.seller = _seller
        self.arbitrator = _arbitrator

@public
def finalize():
    assert msg.sender == self.buyer or msg.sender == self.arbitrator
    send(self.seller, self.balance)

@public
def refund():
    assert msg.sender == self.seller or msg.sender == self.arbitrator
    send(self.buyer, self.balance)

    """

    c = get_contract_with_gas_estimation(arbitration_code, value=1)
    c.setup(t.a1, t.a2, sender=t.k0)
    try:
        c.finalize(sender=t.k1)
        success = True
    except tester.TransactionFailed:
        success = False
    assert not success
    c.finalize(sender=t.k0)

    print('Passed escrow test')


def test_arbitration_code_with_init(t, get_contract_with_gas_estimation):
    arbitration_code_with_init = """
buyer: address
seller: address
arbitrator: address

@public
@payable
def __init__(_seller: address, _arbitrator: address):
    if not self.buyer:
        self.buyer = msg.sender
        self.seller = _seller
        self.arbitrator = _arbitrator

@public
def finalize():
    assert msg.sender == self.buyer or msg.sender == self.arbitrator
    send(self.seller, self.balance)

@public
def refund():
    assert msg.sender == self.seller or msg.sender == self.arbitrator
    send(self.buyer, self.balance)
    """

    c = get_contract_with_gas_estimation(arbitration_code_with_init,
                                         args=[t.a1, t.a2], sender=t.k0, value=1)
    try:
        c.finalize(sender=t.k1)
        success = True
    except t.TransactionFailed:
        success = False
    assert not success
    c.finalize(sender=t.k0)

    print('Passed escrow test with initializer')

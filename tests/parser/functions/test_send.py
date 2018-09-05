def test_send(assert_tx_failed, get_contract):
    send_test = """
@public
def foo():
    send(msg.sender, self.balance + 1)

@public
def fop():
    send(msg.sender, 10)
    """
    c = get_contract(send_test, value=10)
    assert_tx_failed(lambda: c.foo(transact={}))
    c.fop(transact={})
    assert_tx_failed(lambda: c.fop(transact={}))


def test_payable_tx_fail(assert_tx_failed, get_contract, w3):
    code = """
@public
def pay_me() -> bool:
    return True
    """
    c = get_contract(code)
    assert_tx_failed(lambda: c.pay_me(transact={'value': w3.toWei(0.1, 'ether')}))


def test_default_gas(get_contract, w3):
    """ Tests to verify that send to default function will send limited gas (2300), but raw_call can send more."""

    sender_code = """
@public
def test_send(receiver: address):
    send(receiver, 1)

@public
def test_call(receiver: address):
    raw_call(receiver, "", gas=50000, outsize=0, value=1)
    """

    # default function writes variable, this requires more gas than send can pass
    receiver_code = """
last_sender: public(address)

@public
@payable
def __default__():
    self.last_sender = msg.sender
    """

    sender = get_contract(sender_code, value=1)
    receiver = get_contract(receiver_code)

    sender.test_send(receiver.address, transact={'gas': 100000})

    # no value transfer hapenned, variable was not changed
    assert receiver.last_sender() is None
    assert w3.eth.getBalance(sender.address) == 1
    assert w3.eth.getBalance(receiver.address) == 0

    sender.test_call(receiver.address, transact={'gas': 100000})

    # value transfer hapenned, variable was changed
    assert receiver.last_sender() == sender.address
    assert w3.eth.getBalance(sender.address) == 0
    assert w3.eth.getBalance(receiver.address) == 1

def test_send(tx_failed, get_contract):
    send_test = """
@external
def foo():
    send(msg.sender, self.balance + 1)

@external
def fop():
    send(msg.sender, 10)
    """
    c = get_contract(send_test, value=10)
    with tx_failed():
        c.foo(transact={})
    c.fop(transact={})
    with tx_failed():
        c.fop(transact={})


def test_default_gas(get_contract, w3):
    """
    Tests to verify that send to default function will send limited gas (2300),
    but raw_call can send more.
    """

    sender_code = """
@external
def test_send(receiver: address):
    send(receiver, 1)

@external
def test_call(receiver: address):
    raw_call(receiver, b"", gas=50000, max_outsize=0, value=1)
    """

    # default function writes variable, this requires more gas than send can pass
    receiver_code = """
last_sender: public(address)

@external
@payable
def __default__():
    self.last_sender = msg.sender
    """

    sender = get_contract(sender_code, value=1)
    receiver = get_contract(receiver_code)

    sender.test_send(receiver.address, transact={"gas": 100000})

    # no value transfer happened, variable was not changed
    assert receiver.last_sender() is None
    assert w3.eth.get_balance(sender.address) == 1
    assert w3.eth.get_balance(receiver.address) == 0

    sender.test_call(receiver.address, transact={"gas": 100000})

    # value transfer happened, variable was changed
    assert receiver.last_sender() == sender.address
    assert w3.eth.get_balance(sender.address) == 0
    assert w3.eth.get_balance(receiver.address) == 1


def test_send_gas_stipend(get_contract, w3):
    """
    Tests to verify that adding gas stipend to send() will send sufficient gas
    """

    sender_code = """

@external
def test_send_stipend(receiver: address):
    send(receiver, 1, gas=50000)
    """

    # default function writes variable, this requires more gas than
    # send would pass without gas stipend
    receiver_code = """
last_sender: public(address)

@external
@payable
def __default__():
    self.last_sender = msg.sender
    """

    sender = get_contract(sender_code, value=1)
    receiver = get_contract(receiver_code)

    sender.test_send_stipend(receiver.address, transact={"gas": 100000})

    # value transfer happened, variable was changed
    assert receiver.last_sender() == sender.address
    assert w3.eth.get_balance(sender.address) == 0
    assert w3.eth.get_balance(receiver.address) == 1

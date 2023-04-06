def test_throw_on_sending(w3, assert_tx_failed, get_contract_with_gas_estimation):
    code = """
x: public(int128)

@external
def __init__():
    self.x = 123
    """
    c = get_contract_with_gas_estimation(code)

    assert c.x() == 123
    assert w3.eth.get_balance(c.address) == 0
    assert_tx_failed(
        lambda: w3.eth.send_transaction({"to": c.address, "value": w3.toWei(0.1, "ether")})
    )
    assert w3.eth.get_balance(c.address) == 0


def test_basic_default(w3, get_logs, get_contract_with_gas_estimation):
    code = """
event Sent:
    sender: indexed(address)

@external
@payable
def __default__():
    log Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    logs = get_logs(w3.eth.send_transaction({"to": c.address, "value": 10 ** 17}), c, "Sent")
    assert w3.eth.accounts[0] == logs[0].args.sender
    assert w3.eth.get_balance(c.address) == w3.toWei(0.1, "ether")


def test_basic_default_default_param_function(w3, get_logs, get_contract_with_gas_estimation):
    code = """
event Sent:
    sender: indexed(address)

@external
@payable
def fooBar(a: int128 = 12345) -> int128:
    log Sent(ZERO_ADDRESS)
    return a

@external
@payable
def __default__():
    log Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    logs = get_logs(w3.eth.send_transaction({"to": c.address, "value": 10 ** 17}), c, "Sent")
    assert w3.eth.accounts[0] == logs[0].args.sender
    assert w3.eth.get_balance(c.address) == w3.toWei(0.1, "ether")


def test_basic_default_not_payable(w3, assert_tx_failed, get_contract_with_gas_estimation):
    code = """
event Sent:
    sender: indexed(address)

@external
def __default__():
    log Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    assert_tx_failed(lambda: w3.eth.send_transaction({"to": c.address, "value": 10 ** 17}))


def test_multi_arg_default(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@payable
@external
def __default__(arg1: int128):
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code))


def test_always_public(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@internal
def __default__():
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code))


def test_always_public_2(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
event Sent:
    sender: indexed(address)

def __default__():
    log Sent(msg.sender)
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code))


def test_zero_method_id(w3, get_logs, get_contract_with_gas_estimation):
    code = """
event Sent:
    sig: uint256

@external
@payable
# function selector: 0x00000000
def blockHashAskewLimitary(v: uint256) -> uint256:
    log Sent(2)
    return 7

@external
def __default__():
    log Sent(1)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.blockHashAskewLimitary(0) == 7

    logs = get_logs(w3.eth.send_transaction({"to": c.address, "value": 0}), c, "Sent")
    assert 1 == logs[0].args.sig

    logs = get_logs(
        # call blockHashAskewLimitary
        w3.eth.send_transaction({"to": c.address, "value": 0, "data": "0x" + "00" * 36}),
        c,
        "Sent",
    )
    assert 2 == logs[0].args.sig

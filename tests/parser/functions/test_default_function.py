
def test_throw_on_sending(w3, assert_tx_failed, get_contract_with_gas_estimation):
    code = """
x: public(int128)

@public
def __init__():
    self.x = 123
    """
    c = get_contract_with_gas_estimation(code)

    assert c.x() == 123
    assert w3.eth.getBalance(c.address) == 0
    assert_tx_failed(lambda: w3.eth.sendTransaction({'to': c.address, 'value': w3.toWei(0.1, 'ether')}))
    assert w3.eth.getBalance(c.address) == 0


def test_basic_default(w3, get_logs, get_contract_with_gas_estimation):
    code = """
Sent: event({sender: indexed(address)})

@public
@payable
def __default__():
    log.Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    logs = get_logs(w3.eth.sendTransaction({'to': c.address, 'value': 10**17}), c, 'Sent')
    assert w3.eth.accounts[0] == logs[0].args.sender
    assert w3.eth.getBalance(c.address) == w3.toWei(0.1, 'ether')


def test_basic_default_default_param_function(w3, get_logs, get_contract_with_gas_estimation):
    code = """
Sent: event({sender: indexed(address)})
@public
@payable
def fooBar(a: int128 = 12345) -> int128:
    log.Sent(ZERO_ADDRESS)
    return a

@public
@payable
def __default__():
    log.Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    logs = get_logs(w3.eth.sendTransaction({'to': c.address, 'value': 10**17}), c, 'Sent')
    assert w3.eth.accounts[0] == logs[0].args.sender
    assert w3.eth.getBalance(c.address) == w3.toWei(0.1, 'ether')


def test_basic_default_not_payable(w3, assert_tx_failed, get_contract_with_gas_estimation):
    code = """
Sent: event({sender: indexed(address)})

@public
def __default__():
    log.Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    assert_tx_failed(lambda: w3.eth.sendTransaction({'to': c.address, 'value': 10**17}))


def test_multi_arg_default(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@payable
@public
def __default__(arg1: int128):
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code))


def test_always_public(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@private
def __default__():
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code))


def test_always_public_2(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
Sent: event({sender: indexed(address)})

def __default__():
    log.Sent(msg.sender)
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code))

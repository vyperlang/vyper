def test_throw_on_sending(w3, tx_failed, get_contract_with_gas_estimation):
    code = """
x: public(int128)

@deploy
def __init__():
    self.x = 123
    """
    c = get_contract_with_gas_estimation(code)

    assert c.x() == 123
    assert w3.eth.get_balance(c.address) == 0
    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "value": w3.to_wei(0.1, "ether")})
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

    logs = get_logs(w3.eth.send_transaction({"to": c.address, "value": 10**17}), c, "Sent")
    assert w3.eth.accounts[0] == logs[0].args.sender
    assert w3.eth.get_balance(c.address) == w3.to_wei(0.1, "ether")


def test_basic_default_default_param_function(w3, get_logs, get_contract_with_gas_estimation):
    code = """
event Sent:
    sender: indexed(address)

@external
@payable
def fooBar(a: int128 = 12345) -> int128:
    log Sent(empty(address))
    return a

@external
@payable
def __default__():
    log Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    logs = get_logs(w3.eth.send_transaction({"to": c.address, "value": 10**17}), c, "Sent")
    assert w3.eth.accounts[0] == logs[0].args.sender
    assert w3.eth.get_balance(c.address) == w3.to_wei(0.1, "ether")


def test_basic_default_not_payable(w3, tx_failed, get_contract_with_gas_estimation):
    code = """
event Sent:
    sender: indexed(address)

@external
def __default__():
    log Sent(msg.sender)
    """
    c = get_contract_with_gas_estimation(code)

    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "value": 10**17})


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


def test_zero_method_id(w3, get_logs, get_contract, tx_failed):
    # test a method with 0x00000000 selector,
    # expects at least 36 bytes of calldata.
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
    c = get_contract(code)

    assert c.blockHashAskewLimitary(0) == 7

    def _call_with_bytes(hexstr):
        # call our special contract and return the logged value
        logs = get_logs(
            w3.eth.send_transaction({"to": c.address, "value": 0, "data": hexstr}), c, "Sent"
        )
        return logs[0].args.sig

    assert 1 == _call_with_bytes("0x")

    # call blockHashAskewLimitary with proper calldata
    assert 2 == _call_with_bytes("0x" + "00" * 36)

    # call blockHashAskewLimitary with extra trailing bytes in calldata
    assert 2 == _call_with_bytes("0x" + "00" * 37)

    for i in range(4):
        # less than 4 bytes of calldata doesn't match the 0 selector and goes to default
        assert 1 == _call_with_bytes("0x" + "00" * i)

    for i in range(4, 36):
        # match the full 4 selector bytes, but revert due to malformed (short) calldata
        with tx_failed():
            _call_with_bytes(f"0x{'00' * i}")


def test_another_zero_method_id(w3, get_logs, get_contract, tx_failed):
    # test another zero method id but which only expects 4 bytes of calldata
    code = """
event Sent:
    sig: uint256

@external
@payable
# function selector: 0x00000000
def wycpnbqcyf() -> uint256:
    log Sent(2)
    return 7

@external
def __default__():
    log Sent(1)
    """
    c = get_contract(code)

    assert c.wycpnbqcyf() == 7

    def _call_with_bytes(hexstr):
        # call our special contract and return the logged value
        logs = get_logs(
            w3.eth.send_transaction({"to": c.address, "value": 0, "data": hexstr}), c, "Sent"
        )
        return logs[0].args.sig

    assert 1 == _call_with_bytes("0x")

    # call wycpnbqcyf
    assert 2 == _call_with_bytes("0x" + "00" * 4)

    # too many bytes ok
    assert 2 == _call_with_bytes("0x" + "00" * 5)

    # "right" method id but by accident - not enough bytes.
    for i in range(4):
        assert 1 == _call_with_bytes("0x" + "00" * i)


def test_partial_selector_match_trailing_zeroes(w3, get_logs, get_contract):
    code = """
event Sent:
    sig: uint256

@external
@payable
# function selector: 0xd88e0b00
def fow() -> uint256:
    log Sent(2)
    return 7

@external
def __default__():
    log Sent(1)
    """
    c = get_contract(code)

    # sanity check - we can call c.fow()
    assert c.fow() == 7

    def _call_with_bytes(hexstr):
        # call our special contract and return the logged value
        logs = get_logs(
            w3.eth.send_transaction({"to": c.address, "value": 0, "data": hexstr}), c, "Sent"
        )
        return logs[0].args.sig

    # check we can call default function
    assert 1 == _call_with_bytes("0x")

    # check fow() selector is 0xd88e0b00
    assert 2 == _call_with_bytes("0xd88e0b00")

    # check calling d88e0b with no trailing zero goes to fallback instead of reverting
    assert 1 == _call_with_bytes("0xd88e0b")

def test_unreachable_refund(w3, get_contract):
    code = """
@external
def foo():
    assert msg.sender != msg.sender, UNREACHABLE
    """

    c = get_contract(code)
    a0 = w3.eth.accounts[0]
    gas_sent = 10**6
    tx_hash = c.foo(transact={"from": a0, "gas": gas_sent, "gasPrice": 10})
    tx_receipt = w3.eth.get_transaction_receipt(tx_hash)

    assert tx_receipt["status"] == 0
    assert tx_receipt["gasUsed"] == gas_sent  # Drains all gains sent


def test_basic_unreachable(w3, get_contract, tx_failed):
    code = """
@external
def foo(val: int128) -> bool:
    assert val > 0, UNREACHABLE
    assert val == 2, UNREACHABLE
    return True
    """

    c = get_contract(code)

    assert c.foo(2) is True

    with tx_failed(exc_text="Invalid opcode 0xfe"):
        c.foo(1)
    with tx_failed(exc_text="Invalid opcode 0xfe"):
        c.foo(-1)
    with tx_failed(exc_text="Invalid opcode 0xfe"):
        c.foo(-2)


def test_basic_call_unreachable(w3, get_contract, tx_failed):
    code = """

@view
@internal
def _test_me(val: int128) -> bool:
    return val == 33

@external
def foo(val: int128) -> int128:
    assert self._test_me(val), UNREACHABLE
    return -123
    """

    c = get_contract(code)

    assert c.foo(33) == -123

    with tx_failed(exc_text="Invalid opcode 0xfe"):
        c.foo(1)
    with tx_failed(exc_text="Invalid opcode 0xfe"):
        c.foo(-1)


def test_raise_unreachable(w3, get_contract, tx_failed):
    code = """
@external
def foo():
    raise UNREACHABLE
    """

    c = get_contract(code)

    with tx_failed(exc_text="Invalid opcode 0xfe"):
        c.foo()

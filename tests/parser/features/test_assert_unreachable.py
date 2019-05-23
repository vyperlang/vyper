from eth_tester.exceptions import (
    TransactionFailed,
)
import pytest


def test_assure_refund(w3, get_contract):
    code = """
@public
def foo():
    assert 1 == 2, UNREACHABLE
    """

    c = get_contract(code)
    a0 = w3.eth.accounts[0]
    gas_sent = 10**6
    tx_hash = c.foo(transact={'from': a0, 'gas': gas_sent, 'gasPrice': 10})
    tx_receipt = w3.eth.getTransactionReceipt(tx_hash)

    assert tx_receipt['status'] == 0
    assert tx_receipt['gasUsed'] == gas_sent  # Drains all gains sent


def test_basic_unreachable(w3, get_contract, assert_tx_failed):
    code = """
@public
def foo(val: int128) -> bool:
    assert val > 0, UNREACHABLE
    assert val == 2, UNREACHABLE
    return True
    """

    c = get_contract(code)

    assert c.foo(2) is True

    assert_tx_failed(lambda: c.foo(1))
    assert_tx_failed(lambda: c.foo(-1))

    with pytest.raises(TransactionFailed) as e_info:
        c.foo(-2)

    assert 'Invalid opcode 0xf' in e_info.value.args[0]


def test_basic_call_unreachable(w3, get_contract, assert_tx_failed):
    code = """

@constant
@private
def _test_me(val: int128) -> bool:
    return val == 33

@public
def foo(val: int128) -> int128:
    assert self._test_me(val), UNREACHABLE
    return -123
    """

    c = get_contract(code)

    assert c.foo(33) == -123

    assert_tx_failed(lambda: c.foo(1))
    assert_tx_failed(lambda: c.foo(1))
    assert_tx_failed(lambda: c.foo(-1))

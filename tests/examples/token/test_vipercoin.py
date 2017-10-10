import pytest

from ethereum import utils
from ethereum.abi import ValueOutOfBounds
from ethereum.tools import tester


TOKEN_NAME = "Vipercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)


@pytest.fixture
def token_tester():
    t = tester
    tester.s = t.Chain()
    from viper import compiler
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/token/vipercoin.v.py').read()
    tester.c = tester.s.contract(
        contract_code,
        language='viper',
        args=[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY]
    )
    return tester


@pytest.fixture
def assert_tx_failed():
    def assert_tx_failed(tester, function_to_test, exception=tester.TransactionFailed):
        initial_state = tester.s.snapshot()
        with pytest.raises(exception):
            function_to_test()
        tester.s.revert(initial_state)
    return assert_tx_failed


def test_initial_state(token_tester):
    assert token_tester.c.totalSupply() == TOKEN_TOTAL_SUPPLY == token_tester.c.balanceOf(token_tester.accounts[0])
    assert token_tester.c.balanceOf(token_tester.accounts[1]) == 0


def test_transfer(token_tester, assert_tx_failed):

    # Basic transfer.
    assert token_tester.c.transfer(token_tester.accounts[1], 1) is True
    assert token_tester.c.balanceOf(token_tester.accounts[1]) == 1
    assert token_tester.c.balanceOf(token_tester.accounts[0]) == TOKEN_TOTAL_SUPPLY - 1

    # Some edge cases:

    # more than allowed
    assert token_tester.c.transfer(token_tester.accounts[1], TOKEN_TOTAL_SUPPLY) is False

    # Negative transfer value.
    assert_tx_failed(
        tester=token_tester,
        function_to_test=lambda: tester.c.transfer(token_tester.accounts[1], -1),
        exception=ValueOutOfBounds
    )


def test_approve_allowance(token_tester):
    assert token_tester.c.allowance(token_tester.accounts[0], token_tester.accounts[1]) == 0
    assert token_tester.c.approve(token_tester.accounts[1], 10) is True
    assert token_tester.c.allowance(token_tester.accounts[0], token_tester.accounts[1]) == 10


def test_transferFrom(token_tester, assert_tx_failed):
    a0 = token_tester.accounts[0]
    a1 = token_tester.accounts[1]
    k1 = token_tester.k1
    a2 = token_tester.accounts[2]
    k2 = token_tester.k2
    contract = token_tester.c

    # Allow 10 token transfers. Account a1 is allowed to spend 10 tokens of a0's account.
    ALLOWANCE = 10
    assert contract.approve(a1, 10) is True
    assert contract.allowance(a0, a1) == ALLOWANCE

    assert contract.transferFrom(a0, a2, 3, sender=k1) is True  # a1 may transfer.
    assert contract.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - 3
    assert contract.balanceOf(a1) == 0
    assert contract.balanceOf(a2) == 3
    assert contract.allowance(a0, a1) == ALLOWANCE - 3

    # a2 may not transfer.
    assert contract.transferFrom(a0, a2, ALLOWANCE, sender=k2) is False

    # Negative transfer value.
    assert_tx_failed(
        tester=token_tester,
        function_to_test=lambda: contract.transferFrom(a0, a2, -1, sender=k1),
        exception=ValueOutOfBounds
    )

    # Transfer more than allowance:
    assert contract.transferFrom(a0, a2, 8, sender=k1) is False
    assert contract.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - 3
    assert contract.balanceOf(a1) == 0
    assert contract.balanceOf(a2) == 3
    assert contract.allowance(a0, a1) == ALLOWANCE - 3

    # Transfer exact amount left in allowance:
    allowance_left = contract.allowance(a0, a1)
    assert contract.transferFrom(a0, a2, allowance_left, sender=k1) is True
    assert contract.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - ALLOWANCE
    assert contract.balanceOf(a1) == 0
    assert contract.balanceOf(a2) == ALLOWANCE
    assert contract.allowance(a0, a1) == 0


def test_transfer_event(token_tester):
    a0 = token_tester.accounts[0]
    a1 = token_tester.accounts[1]
    k1 = token_tester.k1
    a2 = token_tester.accounts[2]

    contract = token_tester.c
    chain = token_tester.s

    assert contract.transfer(a1, 1) is True

    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('Transfer(address,address,uint256)', 'utf-8')))

    assert logs.topics[0] == event_id
    assert contract.translator.event_data[event_id] == {
        'types': ['address', 'address', 'uint256'],
        'name': 'Transfer', 'names': ['_from', '_to', '_value'],
        'indexed': [True, True, False], 'anonymous': False
    }

    assert contract.translator.decode_event(logs.topics, logs.data) == {
        '_from': '0x' + a0.hex(),
        '_to': '0x' + a1.hex(),
        '_value': 1,
        '_event_type': b'Transfer'
    }

    # Test event using transferFrom
    assert contract.approve(a1, 10) is True  # approve 10 token transfers to a1.
    assert contract.transferFrom(a0, a2, 4, sender=k1)  # transfer to a2, as a1, from a0's funds.

    logs = chain.head_state.receipts[-1].logs[-1]

    assert logs.topics[0] == event_id
    assert contract.translator.decode_event(logs.topics, logs.data) == {
        '_from': '0x' + a0.hex(),
        '_to': '0x' + a2.hex(),
        '_value': 4,
        '_event_type': b'Transfer'
    }


def test_approval_event(token_tester):
    a0 = token_tester.accounts[0]
    a1 = token_tester.accounts[1]

    contract = token_tester.c
    chain = token_tester.s

    assert contract.approve(a1, 10) is True  # approve 10 token transfers to a1.

    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('Approval(address,address,uint256)', 'utf-8')))

    assert logs.topics[0] == event_id
    assert contract.translator.decode_event(logs.topics, logs.data) == {
        '_owner': '0x' + a0.hex(),
        '_spender': '0x' + a1.hex(),
        '_value': 10,
        '_event_type': b'Approval'
    }

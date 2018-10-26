import pytest

from web3.exceptions import ValidationError


TOKEN_NAME = b"Vypercoin"
TOKEN_SYMBOL = b"FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)


@pytest.fixture
def c(get_contract):
    with open('examples/tokens/vypercoin.vy') as f:
        return get_contract(
            f.read(),
            *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY]
        )


def pad_bytes32(instr):
    """ Pad a string \x00 bytes to return correct bytes32 representation. """
    return instr.ljust(32, b'\x00')


def test_initial_state(c, w3):
    a0, a1 = w3.eth.accounts[:2]
    assert c.totalSupply() == TOKEN_TOTAL_SUPPLY == c.balanceOf(a0)
    assert c.balanceOf(a1) == 0
    assert c.symbol() == pad_bytes32(TOKEN_SYMBOL)
    assert c.name() == pad_bytes32(TOKEN_NAME)


def test_transfer(w3, c, assert_tx_failed):
    a0, a1 = w3.eth.accounts[:2]

    # Basic transfer.
    c.transfer(a1, 1, transact={})
    assert c.balanceOf(a1) == 1
    assert c.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - 1

    # more than allowed
    assert_tx_failed(lambda: c.transfer(a1, TOKEN_TOTAL_SUPPLY))

    # Negative transfer value.
    assert_tx_failed(
        function_to_test=lambda: c.transfer(a1, -1),
        exception=ValidationError
    )


def test_approve_allowance(w3, c):
    a0, a1 = w3.eth.accounts[:2]
    assert c.allowance(a0, a1) == 0
    c.approve(a1, 10, transact={})
    assert c.allowance(a0, a1) == 10


def test_transferFrom(w3, c, assert_tx_failed):
    a0, a1, a2 = w3.eth.accounts[:3]

    # Allow 10 token transfers. Account a1 is allowed to spend 10 tokens of a0's account.
    ALLOWANCE = 10
    c.approve(a1, ALLOWANCE, transact={}) is True
    assert c.allowance(a0, a1) == ALLOWANCE

    c.transferFrom(a0, a2, 3, transact={'from': a1})  # a1 may transfer.
    assert c.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - 3
    assert c.balanceOf(a1) == 0
    assert c.balanceOf(a2) == 3
    assert c.allowance(a0, a1) == ALLOWANCE - 3

    # a2 may not transfer.
    assert_tx_failed(lambda: c.transferFrom(a0, a2, ALLOWANCE, transact={'from': a2}))

    # Negative transfer value.
    assert_tx_failed(
        function_to_test=lambda: c.transferFrom(a0, a2, -1, transact={'from': a1}),
        exception=ValidationError
    )

    # Transfer more than allowance:
    assert_tx_failed(lambda: c.transferFrom(a0, a2, 8, transact={'from': a1}))
    assert c.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - 3
    assert c.balanceOf(a1) == 0
    assert c.balanceOf(a2) == 3
    assert c.allowance(a0, a1) == ALLOWANCE - 3

    # Transfer exact amount left in allowance:
    allowance_left = c.allowance(a0, a1)
    c.transferFrom(a0, a2, allowance_left, transact={'from': a1})
    assert c.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - ALLOWANCE
    assert c.balanceOf(a1) == 0
    assert c.balanceOf(a2) == ALLOWANCE
    assert c.allowance(a0, a1) == 0


def test_transfer_event(w3, c, get_logs):
    a0, a1, a2 = w3.eth.accounts[:3]

    logs = get_logs(c.transfer(a1, 1, transact={}), c, 'Transfer')

    args = logs[0].args
    assert args._from == a0
    assert args._to == a1
    assert args._value == 1

    # Test event using transferFrom
    c.approve(a1, 10, transact={})  # approve 10 token transfers to a1.
    logs = get_logs(c.transferFrom(a0, a2, 4, transact={'from': a1}), c, 'Transfer')  # transfer to a2, as a1, from a0's funds.

    args = logs[0].args
    assert args._from == a0
    assert args._to == a2
    assert args._value == 4


def test_approval_event(w3, c, get_logs):
    a0, a1 = w3.eth.accounts[:2]

    logs = get_logs(c.approve(a1, 10, transact={}), c, 'Approval')  # approve 10 token transfers to a1.

    args = logs[0].args
    assert args._owner == a0
    assert args._spender == a1
    assert args._value == 10

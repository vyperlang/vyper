import pytest
from web3.exceptions import ValidationError


TOKEN_NAME = b"Vypercoin"
TOKEN_SYMBOL = b"FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)


@pytest.fixture
def erc20(get_contract):
    with open('examples/tokens/vypercoin.vy') as f:
        contract = get_contract(f.read(), *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])
    return contract


@pytest.fixture
def erc20_caller(erc20, get_contract):
    erc20_caller_code = """
token_address: address(ERC20)

@public
def __init__(token_addr: address):
    self.token_address = token_addr

@public
def name() -> bytes32:
    return self.token_address.name()

@public
def symbol() -> bytes32:
    return self.token_address.symbol()

@public
def decimals() -> uint256:
    return self.token_address.decimals()

@public
def balanceOf(_owner: address) -> uint256:
    return self.token_address.balanceOf(_owner)

@public
def totalSupply() -> uint256:
    return self.token_address.totalSupply()

@public
def transfer(_to: address, _value: uint256) -> bool:
    return self.token_address.transfer(_to, _value)

@public
def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
    return self.token_address.transferFrom(_from, _to, _value)

@public
def allowance(_owner: address, _spender: address) -> uint256:
    return self.token_address.allowance(_owner, _spender)
    """
    return get_contract(erc20_caller_code, *[erc20.address])


def pad_bytes32(instr):
    """ Pad a string \x00 bytes to return correct bytes32 representation. """
    return instr + (32 - len(instr)) * b'\x00'


def test_initial_state(w3, erc20_caller):
    assert erc20_caller.totalSupply() == TOKEN_TOTAL_SUPPLY == erc20_caller.balanceOf(w3.eth.accounts[0])
    assert erc20_caller.balanceOf(w3.eth.accounts[1]) == 0
    assert erc20_caller.name() == pad_bytes32(TOKEN_NAME)
    assert erc20_caller.symbol() == pad_bytes32(TOKEN_SYMBOL)
    assert erc20_caller.decimals() == TOKEN_DECIMALS


def test_call_transfer(w3, erc20, erc20_caller, assert_tx_failed):

    # Basic transfer.
    erc20.transfer(erc20_caller.address, 10, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 10
    erc20_caller.transfer(w3.eth.accounts[1], 10, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 0
    assert erc20.balanceOf(w3.eth.accounts[1]) == 10

    # more than allowed
    assert_tx_failed(lambda: erc20_caller.transfer(w3.eth.accounts[1], TOKEN_TOTAL_SUPPLY))

    # Negative transfer value.
    assert_tx_failed(
        function_to_test=lambda: erc20_caller.transfer(w3.eth.accounts[1], -1),
        exception=ValidationError
    )


def test_caller_approve_allowance(w3, erc20, erc20_caller):
    assert erc20_caller.allowance(erc20.address, erc20_caller.address) == 0
    assert erc20.approve(erc20_caller.address, 10, transact={})
    assert erc20_caller.allowance(w3.eth.accounts[0], erc20_caller.address) == 10


def test_caller_tranfer_from(w3, erc20, erc20_caller, assert_tx_failed):
    # Cannot transfer tokens that are unavailable
    assert_tx_failed(lambda: erc20_caller.transferFrom(w3.eth.accounts[0], erc20_caller.address, 10))
    assert erc20.balanceOf(erc20_caller.address) == 0
    assert erc20.approve(erc20_caller.address, 10, transact={})
    erc20_caller.transferFrom(w3.eth.accounts[0], erc20_caller.address, 5, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 5
    assert erc20_caller.allowance(w3.eth.accounts[0], erc20_caller.address) == 5
    erc20_caller.transferFrom(w3.eth.accounts[0], erc20_caller.address, 3, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 8
    assert erc20_caller.allowance(w3.eth.accounts[0], erc20_caller.address) == 2

import pytest
from web3.exceptions import ValidationError

TOKEN_NAME = "Vypercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = 21 * 10**6
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10**TOKEN_DECIMALS)


@pytest.fixture
def erc20(get_contract):
    with open("examples/tokens/ERC20.vy") as f:
        contract = get_contract(
            f.read(), *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY]
        )
    return contract


@pytest.fixture
def erc20_caller(erc20, get_contract):
    erc20_caller_code = """
interface ERC20Contract:
    def name() -> String[64]: view
    def symbol() -> String[32]: view
    def decimals() -> uint256: view
    def balanceOf(_owner: address) -> uint256: view
    def totalSupply() -> uint256: view
    def transfer(_to: address, _amount: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _amount: uint256) -> bool: nonpayable
    def allowance(_owner: address, _spender: address) -> uint256: nonpayable

token_address: ERC20Contract

@deploy
def __init__(token_addr: address):
    self.token_address = ERC20Contract(token_addr)

@external
def name() -> String[64]:
    return staticcall self.token_address.name()

@external
def symbol() -> String[32]:
    return staticcall self.token_address.symbol()

@external
def decimals() -> uint256:
    return staticcall self.token_address.decimals()

@external
def balanceOf(_owner: address) -> uint256:
    return staticcall self.token_address.balanceOf(_owner)

@external
def totalSupply() -> uint256:
    return staticcall self.token_address.totalSupply()

@external
def transfer(_to: address, _value: uint256) -> bool:
    return extcall self.token_address.transfer(_to, _value)

@external
def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
    return extcall self.token_address.transferFrom(_from, _to, _value)

@external
def allowance(_owner: address, _spender: address) -> uint256:
    return extcall self.token_address.allowance(_owner, _spender)
    """
    return get_contract(erc20_caller_code, *[erc20.address])


def test_initial_state(w3, erc20_caller):
    assert erc20_caller.totalSupply() == TOKEN_TOTAL_SUPPLY
    assert erc20_caller.balanceOf(w3.eth.accounts[0]) == TOKEN_TOTAL_SUPPLY
    assert erc20_caller.balanceOf(w3.eth.accounts[1]) == 0
    assert erc20_caller.name() == TOKEN_NAME
    assert erc20_caller.symbol() == TOKEN_SYMBOL
    assert erc20_caller.decimals() == TOKEN_DECIMALS


def test_call_transfer(w3, erc20, erc20_caller, tx_failed):
    # Basic transfer.
    erc20.transfer(erc20_caller.address, 10, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 10
    erc20_caller.transfer(w3.eth.accounts[1], 10, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 0
    assert erc20.balanceOf(w3.eth.accounts[1]) == 10

    # more than allowed
    with tx_failed():
        erc20_caller.transfer(w3.eth.accounts[1], TOKEN_TOTAL_SUPPLY)

    # Negative transfer value.
    with tx_failed(ValidationError):
        erc20_caller.transfer(w3.eth.accounts[1], -1)


def test_caller_approve_allowance(w3, erc20, erc20_caller):
    assert erc20_caller.allowance(erc20.address, erc20_caller.address) == 0
    assert erc20.approve(erc20_caller.address, 10, transact={})
    assert erc20_caller.allowance(w3.eth.accounts[0], erc20_caller.address) == 10


def test_caller_tranfer_from(w3, erc20, erc20_caller, tx_failed):
    # Cannot transfer tokens that are unavailable
    with tx_failed():
        erc20_caller.transferFrom(w3.eth.accounts[0], erc20_caller.address, 10)
    assert erc20.balanceOf(erc20_caller.address) == 0
    assert erc20.approve(erc20_caller.address, 10, transact={})
    erc20_caller.transferFrom(w3.eth.accounts[0], erc20_caller.address, 5, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 5
    assert erc20_caller.allowance(w3.eth.accounts[0], erc20_caller.address) == 5
    erc20_caller.transferFrom(w3.eth.accounts[0], erc20_caller.address, 3, transact={})
    assert erc20.balanceOf(erc20_caller.address) == 8
    assert erc20_caller.allowance(w3.eth.accounts[0], erc20_caller.address) == 2

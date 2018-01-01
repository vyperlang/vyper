import pytest
from ethereum.abi import ValueOutOfBounds

TOKEN_NAME = "Vipercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)


@pytest.fixture
def erc20(get_contract):
    erc20_code = open('examples/tokens/vipercoin.v.py').read()
    return get_contract(erc20_code, args=[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])


@pytest.fixture
def erc20_caller(erc20, get_contract):
    erc20_caller_code = """
token_address: address(ERC20)

@public
def __init__(token_addr: address):
    self.token_address = token_addr

@public
def symbol() -> bytes32:
    return self.token_address.symbol()

@public
def balanceOf(_owner: address) -> num256:
    return self.token_address.balanceOf(_owner)

@public
def totalSupply() -> num256:
    return self.token_address.totalSupply()

@public
def transfer(_to: address, _value: num256) -> bool:
    return self.token_address.transfer(_to, _value)

@public
def transferFrom(_from: address, _to: address, _value: num(num256)) -> bool:
    return self.token_address.transferFrom(_from, _to, _value)

@public
def allowance(_owner: address, _spender: address) -> num256:
    return self.token_address.allowance(_owner, _spender)
    """
    return get_contract(erc20_caller_code, args=[erc20.address])


def pad_bytes32(instr):
    """ Pad a string \x00 bytes to return correct bytes32 representation. """
    bstr = instr.encode()
    return bstr + (32 - len(bstr)) * b'\x00'


def test_initial_state(t, erc20_caller):
    assert erc20_caller.totalSupply() == TOKEN_TOTAL_SUPPLY == erc20_caller.balanceOf(t.a0)
    assert erc20_caller.balanceOf(t.a1) == 0
    assert erc20_caller.symbol() == pad_bytes32(TOKEN_SYMBOL)


def test_call_transfer(t, chain, erc20, erc20_caller, assert_tx_failed):

    # Basic transfer.
    erc20.transfer(erc20_caller.address, 10)
    assert erc20.balanceOf(erc20_caller.address) == 10
    erc20_caller.transfer(t.a1, 10)
    assert erc20.balanceOf(erc20_caller.address) == 0
    assert erc20.balanceOf(t.a1) == 10

    # more than allowed
    assert_tx_failed(lambda: erc20_caller.transfer(t.a1, TOKEN_TOTAL_SUPPLY))

    t.s = chain
    # Negative transfer value.
    assert_tx_failed(
        function_to_test=lambda: erc20_caller.transfer(t.a1, -1),
        exception=ValueOutOfBounds
    )


def test_caller_approve_allowance(t, erc20, erc20_caller):
    assert erc20_caller.allowance(erc20.address, erc20_caller.address) == 0
    assert erc20.approve(erc20_caller.address, 10)
    assert erc20_caller.allowance(t.a0, erc20_caller.address) == 10


def test_caller_tranfer_from(t, erc20, erc20_caller, assert_tx_failed):
    # Cannot transfer tokens that are unavailable
    assert_tx_failed(lambda: erc20_caller.transferFrom(t.a0, erc20_caller.address, 10))
    assert erc20.balanceOf(erc20_caller.address) == 0
    assert erc20.approve(erc20_caller.address, 10)
    erc20_caller.transferFrom(t.a0, erc20_caller.address, 5)
    assert erc20.balanceOf(erc20_caller.address) == 5
    assert erc20_caller.allowance(t.a0, erc20_caller.address) == 5
    erc20_caller.transferFrom(t.a0, erc20_caller.address, 3)
    assert erc20.balanceOf(erc20_caller.address) == 8
    assert erc20_caller.allowance(t.a0, erc20_caller.address) == 2

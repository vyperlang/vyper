import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract, assert_tx_failed
from viper.exceptions import StructureException, VariableDeclarationException, InvalidTypeException

def test_erc20_abi_transfer():
    # TODO: Once erc20 is merged build off that
    erc20_code = """
# Viper Port of MyToken
# THIS CONTRACT HAS NOT BEEN AUDITED!
# ERC20 details at:
# https://theethereum.wiki/w/index.php/ERC20_Token_Standard
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-20-token-standard.md


# Events of the token.
Transfer: __log__({_from: indexed(address), _to: indexed(address), _value: num256})
Approval: __log__({_owner: indexed(address), _spender: indexed(address), _value: num256})


# Variables of the token.
name: bytes32
symbol: bytes32
totalSupply: num
decimals: num
balances: num[address]
allowed: num[address][address]


def __init__(_name: bytes32, _symbol: bytes32, _decimals: num, _initialSupply: num):

    self.name = _name
    self.symbol = _symbol
    self.decimals = _decimals
    self.totalSupply = _initialSupply * 10 ** _decimals
    self.balances[msg.sender] = self.totalSupply


@constant
def symbol() -> bytes32:

    return self.symbol


# What is the balance of a particular account?
@constant
def balanceOf(_owner: address) -> num256:

    return as_num256(self.balances[_owner])


# Return total supply of token.
@constant
def totalSupply() -> num256:

    return as_num256(self.totalSupply)


# Send `_value` tokens to `_to` from your account
def transfer(_to: address, _amount: num(num256)) -> bool:

    if self.balances[msg.sender] >= _amount and \
       self.balances[_to] + _amount >= self.balances[_to]:

        self.balances[msg.sender] -= _amount  # Subtract from the sender
        self.balances[_to] += _amount  # Add the same to the recipient
        log.Transfer(msg.sender, _to, as_num256(_amount))  # log transfer event.

        return True
    else:
        return False


# Transfer allowed tokens from a specific account to another.
def transferFrom(_from: address, _to: address, _value: num(num256)) -> bool:

    if _value <= self.allowed[_from][msg.sender] and \
       _value <= self.balances[_from]:

        self.balances[_from] -= _value  # decrease balance of from address.
        self.allowed[_from][msg.sender] -= _value  # decrease allowance.
        self.balances[_to] += _value  # incease balance of to address.
        log.Transfer(_from, _to, as_num256(_value))  # log transfer event.

        return True
    else:
        return False


# Allow _spender to withdraw from your account, multiple times, up to the _value amount.
# If this function is called again it overwrites the current allowance with _value.
def approve(_spender: address, _amount: num(num256)) -> bool:

    self.allowed[msg.sender][_spender] = _amount
    log.Approval(msg.sender, _spender, as_num256(_amount))

    return True


# Get the allowence an address has to spend anothers' token.
def allowance(_owner: address, _spender: address) -> num256:

    return as_num256(self.allowed[_owner][_spender])

"""

    code = """
token_address: address(ERC20)

def __init__(token_addr: address):
    self.token_address = token_addr

def transfer(to: address, value: num256):
    self.token_address.transfer(to, value)
    """
    TOKEN_NAME = "Vipercoin"
    TOKEN_SYMBOL = "FANG"
    TOKEN_DECIMALS = 18
    TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
    TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)
    erc20 = get_contract(erc20_code, args=[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])
    c = get_contract(code, args=[erc20.address])
    erc20.transfer(c.address, 10)
    assert erc20.balanceOf(c.address) == 10
    c.transfer(t.a1, 10)
    assert erc20.balanceOf(c.address) == 0
    assert erc20.balanceOf(t.a1) == 10

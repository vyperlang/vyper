# Viper Port of MyToken
# THIS HAS NOT BEEN AUDITED!
# ERC20 details at:
# https://theethereum.wiki/w/index.php/ERC20_Token_Standard
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-20-token-standard.md


# Variables of the token
name: bytes32
symbol: bytes32
totalSupply: num
decimals: num
balances: num[address]
allowed: num[address][address]


def __init__(
        _name: bytes32, _symbol: bytes32, _decimals: num, initialSupply: num):

    self.name = _name
    self.symbol = _symbol
    self.decimals = _decimals
    self.totalSupply = initialSupply
    self.balances[msg.sender] = initialSupply


# What is the balance of a particular account?
def balanceOf(_owner: address) -> num256:
    return as_num256(self.balances[_owner])


# Return total supply of token.
def totalSupply():
    return as_num256(self.totalSupply)


# Send `_value` tokens to `_to` from your account
def transfer(_to: address, _amount: num(num256)) -> bool:

    if self.balances[msg.sender] > _amount and \
       self.balances[_to] + _amount > self.balances[_to]:

        self.balances[msg.sender] -= _amount  # Subtract from the sender
        self.balances[_to] += _amount  # Add the same to the recipient

        return True
    else:
        return False


# Allow _spender to withdraw from your account, multiple times, up to the _value amount.
# If this function is called again it overwrites the current allowance with _value.
def approve(_spender: address, _amount: num(num256)) -> bool:
    self.allowed[msg.sender][_spender] = _amount
    return True


# Get the allowence an address has to spend anothers' token.
def allowance(_owner: address, _spender: address) -> num256:
    return as_num256(self.allowed[_owner][_spender])

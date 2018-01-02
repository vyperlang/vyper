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


@public
def __init__(_name: bytes32, _symbol: bytes32, _decimals: num, _initialSupply: num):

    self.name = _name
    self.symbol = _symbol
    self.decimals = _decimals
    self.totalSupply = _initialSupply * 10 ** _decimals
    self.balances[msg.sender] = self.totalSupply


@public
@constant
def symbol() -> bytes32:

    return self.symbol


# What is the balance of a particular account?
@public
@constant
def balanceOf(_owner: address) -> num256:

    return as_num256(self.balances[_owner])


# Return total supply of token.
@public
@constant
def totalSupply() -> num256:

    return as_num256(self.totalSupply)


# Send `_value` tokens to `_to` from your account
@public
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
@public
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
@public
def approve(_spender: address, _amount: num(num256)) -> bool:

    self.allowed[msg.sender][_spender] = _amount
    log.Approval(msg.sender, _spender, as_num256(_amount))

    return True


# Get the allowence an address has to spend anothers' token.
@public
def allowance(_owner: address, _spender: address) -> num256:

    return as_num256(self.allowed[_owner][_spender])

# @dev Implementation of ERC-777 token standard.
# @author Carl Farterson (@carlfarterson)
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-777.md

# from vyper.interfaces import ERC777

# implements: ERC777

### @dev Emitted when `value` tokens are moved from one account (`from`)
###      to another (`to`).
### @dev Note that `value` may be zero.
event Transfer:
    sender: indexed(address)
    reciver: indexed(address)
    value: uint256
### @dev Emitted when the allowance of a `spender` for an `owner` is set by
###      a call to {approve}. `value` is the new allowance.
event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256
### @dev TODO
event Sent:
    operator: indexed(address)
    sender: indexed(address)
    to: indexed(address)
    amount: uint256
    data: bytes32
    operatorData: bytes32
### @dev TODO
event Minted:
    operator: indexed(address)
    to: indexed(address)
    amount: uint256
    data: bytes32
    operatorData: bytes32
### @dev TODO
event Burned:
    operator: indexed(address)
    sender: indexed(address)
    amount: uint256
    data: bytes32
    operatorData: bytes32
### @dev TODO
event AuthorizedOperator:
    operator: indexed(address)
    holder: indexed(address)
### @dev TODO
event RevokedOperator:
    operator: indexed(address)
    holder: indexed(address)


### @dev Name of the token.
name: public(String[64])
### @dev Symbol of the token, usually a shorter version of the name.
symbol: public(String[32])
### @dev Amount of tokens in existence.
totalSupply: public(uint256)
### @dev Returns the smallest part of the token that is not divisible. This
###      means all token operations (creation, movement and destruction) must have
###      amounts that are a multiple of this number.
granularity: uint256 = 1
### @dev Always return `18`, as per EIP-777 
decimals: uint256 = 18

# @dev By declaring `balanceOf` as public, vyper automatically generates a 'balanceOf()' getter
#      method to allow access to account balances.
# @dev The _KeyType will become a required parameter for the getter and it will return _ValueType.
# @dev See: https://vyper.readthedocs.io/en/v0.1.0-beta.8/types.html?highlight=getter#mappings
balanceOf: public(HashMap[address, uint256])

### @dev ERC20-allowances
allowances: HashMap[address, HashMap[address, uint256]]

operators: HashMap[address, HashMap[address, bool]]

defaultOperators: HashMap[address, bool]
defaultOperatorsArray: address[] # TODO: how to declare an array of addresses?
revokedDefaultOperators: HashMap[address, HashMap[address, bool]]

### @dev Mapping of interface id to bool about whether or not it's supported
supportedInterfaces: public(HashMap[bytes32, bool])


# TODO: import keccak library (?)
# Register interfaces
supportedInterfaces[keccak256("ERC777TokensSender")] = True
supportedInterfaces[keccak256("ERC777TokensRecipient")] = True

@external
def __init__(_name: String[64], _symbol: String[32]): # TODO: add defaultOperators
    self.name = _name
    self.symbol = symbol

@external
def transfer(recipient: address, amount: uint256) -> bool:
    """
    @dev Moves `amount` tokens from the caller's account to `recipient`.
    @param recipient Address to receive tokens.
    @param amount Quantity of token sent.
    @return True if operation succeeded, False otherwise.
    """
    assert recipient != ZERO_ADDRESS
    _from: address = msg.sender
    self._callTokensToSend(_from, _from, recipient, amount, '', '')
    self._move(_from, _from, recipient, amount, '', '')
    self._callTokensReceived(_from, _from, recipient, amount, '', '', False)
    return True

@external
def burn(amount: uint256, data: bytes32) -> bool:
    """
    @dev ...
    @param amount ...
    @param data ...
    @return bool
    """
    return self._burn(msg.sender, amount, data, '')

@external
def isOperatorFor(operator: address, holder: address) -> bool:
    """
    @dev ...
    @param operator
    @param holder
    @return bool
    """
    return operator == holder ||
        self.operators[holder][operator] ||
        self.defaultOperators[operator] and
        self.revokedDefaultOperators[holder][operator]

@external
def authorizeOperator(operator: address):
    """
    @dev ...
    @param operator ...
    """
    assert msg.sender == operator
    if self.defaultOperators[operator]:
        delete self.revokedDefaultOperators[msg.sender][operator] # TODO: `delete`
    else:
        self.operators[msg.sender][operator] = True

    log AuthorizedOperator(operator, msg.sender)

@external
def revokeOperator(operator: address):
    """
    @dev ...
    @param operator ...
    """
    assert operator == msg.sender
    if self.defaultOperators[operator]:
        self.revokedDefaultOperators[msg.sender][operator] = True
    else:
        delete self.operators[msg.sender][operator] # TODO: `delete`

    log RevokedOperator(operator, msg.sender)

@view
@external
def defaultOperators() -> address[]:  # TODO: how do  you signify returning an array of addresses?
    return self.defaultOperatorsArray

@external
def operatorSend(sender: address, recipient: address, amount: uint256, data: bytes32, operatorData: bytes32):
    """
    @dev ...
    @param sender ...
    @param recipient ...
    @param amount ...
    @param data ...
    @param operatorData ...
    """
    assert self.isOperatorFor(msg.sender, sender)
    self._send(sender, recipient, amount, data, operatorData, True)

@external
def operatorBurn(account: address, amount: uint256, data: bytes32, operatorData: bytes32):
    """
    @dev ...
    @param account ...
    @param amount ...
    @param data ...
    @param operatorData ...
    """
    assert self.isOperatorFor(msg.sender, account)
    self._burn(account, amount, data, operatorData)

@view
@external
def allowance(holder: address, spender: address) -> uint256:
    """
    @dev ...
    @param holder ...
    @param spender ...
    @return uint256
    """
    return self._allowances[holder][spender]

@external
def approve(spender: address, value: uint256) -> bool:
    """
    @dev ...
    @param spender ...
    @param value ...
    @return bool
    """
    holder: address = msg.sender
    self._approve(holder, spender, value)
    return True

@external
# NOTE: could broken erc20's without a `assert holder != ZERO_ADDRESS`
#   withdraw past tokens sent to `ZERO_ADDRESS`
def transferFrom(holder: address, recipient: address, amount: uint256) -> bool:
    """
    @dev
        Moves `amount` tokens from `sender` to `recipient` using the allowance mechanism.
        `amount` is then deducted from the caller's allowance.
    @param holder ...
    @param recipient ...
    @param amount ...
    @return bool
    """
    assert recipient != ZERO_ADDRESS
    assert holder != ZERO_ADDRESS
    spender: address = msg.sender
    self._callTokensToSend(spender, holder, recipient, amount, '', '')
    self._move(spender, holder, recipient, amount, '', '')
    assert self._allowances[holder][spender] - amount > 0
    self._approve(holder, spender, self._allowances[holder][spender] - amount)
    self._callTokensReceived(spender, holder, recipient, amount, '', '', False)
    return True

@internal
def _mint(account: address, amount: uint256, userData: bytes32, operatorData: bytes32) -> bool:
    """
    @dev Creates `amount` tokens and assigns them to `account`, increasing the total supply.
    @param account ...
    @param amount ...
    @param userData ...
    @param operatorData ...
    @return bool
    """
    assert account != ZERO_ADDRESS
    operator: address = msg.sender
    self._beforeTokenTransfer(operator, ZERO_ADDRESS, account, amount)
    self._totalSupply += amount
    self.balanceOf[account] += amount
    self._callTokensReceived(operator, ZERO_ADDRESS, account, amount, userData, operatorData, True)
    log Minted(operator, account, amount, userData, operatorData)
    log Transfer(ZERO_ADDRESS, account, amount)

# TODO: is `send` a key-word? 
@internal
def _send(_from: address, to: address, amount: uint256, userData: bytes32, operatorData: bytes32, requireReceptionAck: bool):
    """
    @dev Send tokens
    @param from address token holder address
    @param to address recipient address
    @param amount uint256 amount of tokens to transfer
    @param userData bytes extra information provided by the token holder (if any)
    @param operatorData bytes extra information provided by the operator (if any)
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient
    """
    assert _from != ZERO_ADDRESS
    assert to != ZERO_ADDRESS
    operator: address = msg.sender
    self._callTokensToSend(operator, _from, to, amount, userData, operatorData)
    self._move(operator, _from, to, amount, userData, operatorData)
    self._callTokensReceived(operator, _from, to, amount, userData, operatorData, requireReceptionAck)

def _burn(_from: address, amount: uint256, data: bytes32, operatorData: bytes32):
    """
    @dev Burn tokens
    @param _from address token holder address
    @param amount uint256 amount of tokens to burn
    @param data bytes extra information provided by the token holder
    @param operatorData bytes extra information provided by the operator (if any)
    """
    assert account != ZERO_ADDRESS
    operator: address = msg.sender
    self._beforeTokenTransfer(operator, _from, ZERO_ADDRESS, amount)
    self._callTokensToSend(operator, _from, ZERO_ADDRESS, amount, userData, operatorData)
    assert self.balanceOf[_from] - amount > 0
    self._totalSupply -= amount
    self.balanceOf[account] -= amount
    log Burned(operator, _from, amount, data, operatorData)
    log Transfer(_from, ZERO_ADDRESS, amount)

def _move(operator: address, _from: address, to: address, amount: uint256, userData: bytes32, operatorData: bytes32):
    """
    @dev ...
    @param operator ...
    @param _from ...
    @param to ...
    @param amount ...
    @param userData ...
    @param operatorData ...
    """
    _beforeTokenTransfer(operator, _from, to, amount)
    assert self.balanceOf[_from] - amount > 0
    self.balanceOf[_from] -= amount
    self.balanceOf[to] += amount
    log Sent(operator, _from, to, amount, userData, operatorData)
    log Transfer(_from, to, amount)

def _approve(holder: address, spender: address, value: uint256):
    assert holder != ZERO_ADDRESS
     assert sender != ZERO_ADDRESS
     self._allowances[holder][spender] = value
     log Approval(holder, spender, value)

# TODO
def _callTokensToSend(operator: address, _from: address, to: address, amount: uint256, userData: bytes32, operatorData: bytes32):
    """
    @dev ...
    @param operator ...
    @param _from ...
    @param to ...
    @param amount
    @param userData ...
    @param operatorData ...
    """
    pass


# TODO
def _callTokensReceived(operator: address, _from: address, to: address, amount: uint256, userData: bytes32, operatorData: bytes32, requireReceptionAck: bool):
    """
    @dev ...
    @param operator ...
    @param _from ...
    @param to ...
    @param amount ...
    @param userData ...
    @param operatorData ...
    @param requireReceptionAck ...
    """
    pass

def _beforeTokenTransfer(operator: address, _from: address, to: address, amount: uint256):
    pass
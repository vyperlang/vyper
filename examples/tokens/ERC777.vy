# @title Implementation of ERC-777 token standard.
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
def transfer(_to: address, _value: uint256) -> bool:
    """
    @dev Moves `_value` tokens from the caller's account to `_to`.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @return True if operation succeeded, False otherwise.
    """
    assert _to != ZERO_ADDRESS
    _from: address = msg.sender
    self._callTokensToSend(_from, _from, _to, _value, '', '')
    self._move(_from, _from, _to, _value, '', '')
    self._callTokensReceived(_from, _from, _to, _value, '', '', False)
    return True


@external
def burn(_value: uint256, data: bytes32) -> bool:
    """
    @dev Burn an amount (`_value`) of the token of msg.sender.
    @param _value Quantity of token burned.
    @param data Extra information provided (if any).
    @return True if operation succeeded, False otherwise.
    """
    return self._burn(msg.sender, _value, data, '')


@internal
def _burn(_from: address, _value: uint256, userData: bytes32, operatorData: bytes32):
    """
    @dev Burn `_value` tokens from address `_from`.
    @param _from Token holder address.
    @param _value Quantity of tokens burned.
    @param userData Extra information provided by the user (if any).
    @param operatorData Extra information provided by the operator (if any).
    """
    assert account != ZERO_ADDRESS
    operator: address = msg.sender
    
    self._beforeTokenTransfer(operator, _from, ZERO_ADDRESS, _value)
    self._callTokensToSend(operator, _from, ZERO_ADDRESS, _value, userData, operatorData)
    self._totalSupply -= _value
    self.balanceOf[account] -= _value
    log Burned(operator, _from, _value, userData, operatorData)
    log Transfer(_from, ZERO_ADDRESS, _value)


@external
def isOperatorFor(operator: address, holder: address) -> bool:
    """
    @dev ...
    @param operator The address which controls the tokens.
    @param holder The address which holds the tokens.
    @return bool
    """
    return operator == holder ||
        self.operators[holder][operator] ||
        (self.defaultOperators[operator] and
        self.revokedDefaultOperators[holder][operator])


@external
def authorizeOperator(operator: address):
    """
    @dev Make an account an operator of the caller.
    @param operator The address to control tokens.
    """
    assert isOperatorFor(operator, msg.sender)
    if self.defaultOperators[operator]:
        delete self.revokedDefaultOperators[msg.sender][operator] # TODO: `delete`
    else:
        self.operators[msg.sender][operator] = True

    log AuthorizedOperator(operator, msg.sender)


@external
def revokeOperator(operator: address):
    """
    @dev Revoke an account's operator status for the caller.
    @param operator The address to lose operator status.
    """
    assert operator != msg.sender
    if self.defaultOperators[operator]:
        self.revokedDefaultOperators[msg.sender][operator] = True
    else:
        delete self.operators[msg.sender][operator] # TODO: `delete`

    log RevokedOperator(operator, msg.sender)


@view
@external
def defaultOperators():
    return self.defaultOperatorsArray


@external
def operatorSend(sender: address, recipient: address, amount: uint256, data: bytes32, operatorData: bytes32):
    """
    @dev Moves `amount` of tokens from `sender` to `recipient`.
    @dev The caller must be an operator of `sender`.
    @param sender Address to send tokens.
    @param recipient Address to receive tokens.
    @param amount Quantity of token sent.
    @param data Extra information provided (if any).
    @param operatorData Extra information provided by the operator (if any).
    """
    assert self.isOperatorFor(msg.sender, sender)
    self._send(sender, recipient, amount, data, operatorData, True)


@external
def operatorBurn(account: address, amount: uint256, data: bytes32, operatorData: bytes32):
    """
    @dev Destroys `amount` tokens from `account`, reducing the total supply.
    @dev If a send hook is registered for `account`, the corresponding function will
         be called with `data` and `operatorData`.
    @param account Address to burn tokens from.
    @param amount Quantity of token burned.
    @param data Extra information provided (if any).
    @param operatorData Extra information provided by the operator (if any).
    """
    assert self.isOperatorFor(msg.sender, account)
    self._burn(account, amount, data, operatorData)


@view
@external
def allowance(_owner : address, _spender : address) -> uint256:
    """
    @dev Function to check the amount of tokens that an owner allowed to a spender.
    @param _owner The address which owns the tokens.
    @param _spender The address which will spend the tokens.
    @return An uint256 specifying the amount of tokens still available for the spender.
    """
    return self.allowances[_owner][_spender]


@external
def approve(_spender: address, _value: uint256) -> bool:
    """
    @dev Approve the passed address to spend the specified amount of tokens on behalf of msg.sender.
    @param _spender The address which will spend the tokens.
    @param _value Quantity of tokens to approve.
    @return True if approval succeeded, False otherwise.
    """
    holder: address = msg.sender
    self._approve(holder, _spender, _value)
    return True


@internal
def _approve(_holder: address, _spender: address, _value: uint256):
    """
    @dev    Approve the passed address to spend the specified amount of tokens on behalf of msg.sender.
    @param _holder The address which holds the tokens.
    @param _spender The address which will spend the tokens.
    @param _value Quantity of tokens to be spent.
    """
    assert _holder != ZERO_ADDRESS
    assert _spender != ZERO_ADDRESS
    self.allowances[_holder][_spender] = _value
    log Approval(_holder, _spender, _value)


@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    """
    @dev Transfer tokens from one address to another.
    @param _from address The address which you want to send tokens from
    @param _to address The address which you want to transfer to
    @param _value uint256 the amount of tokens to be transferred
    @return True if transfer succeeded, False otherwise.
    """
    assert _to != ZERO_ADDRESS

    # NOTE: vyper does not allow underflows
    #       so the following subtraction would revert on insufficient balance
    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value
    # NOTE: vyper does not allow underflows
    #      so the following subtraction would revert on insufficient allowance
    self.allowances[_from][msg.sender] -= _value
    log Transfer(_from, _to, _value)
    return True


# NOTE: could broken erc20's without a `assert holder != ZERO_ADDRESS`
#   withdraw past tokens sent to `ZERO_ADDRESS`
def transferFrom(_to: address, recipient: address, amount: uint256) -> bool:
    """
    @dev
        Moves `amount` tokens from `sender` to `recipient` using the allowance mechanism.
        `amount` is then deducted from the caller's allowance.
    @param _to ...
    @param recipient Address to receive tokens.
    @param amount Quantity of token transferred.
    @return bool
    """
    assert recipient != ZERO_ADDRESS
    assert _to != ZERO_ADDRESS
    spender: address = msg.sender
    self._callTokensToSend(spender, _to, recipient, amount, '', '')
    self._move(spender, _to, recipient, amount, '', '')
    self._approve(_to, spender, self.allowances[_to][spender] - amount)
    self._callTokensReceived(spender, _to, recipient, amount, '', '', False)
    return True

@internal
def _mint(_to: address, _value: uint256, userData: bytes32, operatorData: bytes32) -> bool:
    """
    @dev Creates `_value` tokens and assigns them to `_to`, increasing the total supply.
    @param _to ...
    @param _value Quantity of token minted.
    @param userData Extra information provided by the token holder (if any).
    @param operatorData Extra information provided by the operator (if any).
    @return bool
    """
    assert _to != ZERO_ADDRESS
    operator: address = msg.sender
    self._beforeTokenTransfer(operator, ZERO_ADDRESS, _to, _value)
    self._totalSupply += _value
    self.balanceOf[_to] += _value
    self._callTokensReceived(operator, ZERO_ADDRESS, _to, _value, userData, operatorData, True)
    log Minted(operator, _to, _value, userData, operatorData)
    log Transfer(ZERO_ADDRESS, _to, _value)

# TODO: is `send` a key-word? 
@internal
def _send(_from: address, to: address, amount: uint256, userData: bytes32, operatorData: bytes32, requireReceptionAck: bool):
    """
    @dev Send `amount` tokens from one address(`_from`) to another address(`to`)
    @param _from Token holder address.
    @param recipient Address to receive tokens.
    @param amount Quantity of token sent.
    @param userData Extra information provided by the token holder (if any).
    @param operatorData Extra information provided by the operator (if any).
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient
    """
    assert _from != ZERO_ADDRESS
    assert to != ZERO_ADDRESS
    operator: address = msg.sender
    self._callTokensToSend(operator, _from, to, amount, userData, operatorData)
    self._move(operator, _from, to, amount, userData, operatorData)
    self._callTokensReceived(operator, _from, to, amount, userData, operatorData, requireReceptionAck)

def _move(operator: address, _from: address, _to: address, _value: uint256, userData: bytes32, operatorData: bytes32):
    """
    @dev ...
    @param operator The address which controls the tokens.
    @param _from The address which holds the tokens.
    @param _to The address to receive tokens.
    @param _value Quantity of token moved.
    @param userData Extra information provided by the token holder (if any).
    @param operatorData Extra information provided by the operator (if any).
    """
    _beforeTokenTransfer(operator, _from, _to, _value)
    # NOTE: vyper does not allow underflows
    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value
    log Sent(operator, _from, _to, _value, userData, operatorData)
    log Transfer(_from, _to, _value)



# TODO
def _callTokensToSend(operator: address, _from: address, _to: address, _value: uint256, userData: bytes32, operatorData: bytes32):
    pass

# TODO
def _callTokensReceived(operator: address, _from: address, _to: address, _value: uint256, userData: bytes32, operatorData: bytes32, requireReceptionAck: bool):
    pass

def _beforeTokenTransfer(operator: address, _from: address, _to: address, _value: uint256):
    pass
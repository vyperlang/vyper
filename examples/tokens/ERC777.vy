# @title Implementation of ERC-777 token standard.
# @author Carl Farterson (@carlfarterson)
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-777.md

from vyper.interfaces import ERC777

implements: ERC777

interface ERC1820Registry:
    def setManager(_address: address, _newManager: address): pass
    def getManager(_address: address) -> address: view
    def setInterfaceImplementer(_address: address, _interfaceHash: bytes32, _implementer: address): pass
    def getInterfaceImplementer(_address: address, _interfaceHash: bytes32) -> address: view
    # TODO: default length of string?
    def interfaceHash(_interfaceName: string) -> bytes32: pass
    def updateERC165Cache(_interfaceName: string): pass
    # TODO: bytes4 vs. bytes32?
    def implementsERC165Interface(_address: address, _interfaceId: bytes4) -> bool: view
    def implementsERC165InterfaceNoCache(_address: address, _interfaceId: bytes4) -> bool: view
    event InterfaceImplementerSet:
        _address: indexed(address)
        _interfaceHash: bytes32
        _implementer: indexed(address)
    event ManagerChanged:
        _address: indexed(address)
        _newManager: indexed(address)
    

interface ERC1820ImplementerInterface:
    def canImplementInterfaceForAddress(
        _interfaceHash: bytes32,
        _address: address
    ) -> bytes32: view

interface ERC777Recipient:
    def tokensReceived(
        _operator: address,
        _from: address,
        _to: address,
        _value: uint256,
        _data: bytes32,
        _operatorData: bytes32
    ) -> bool: view

interface ERC777Sender:
    def tokensToSend(
        _operator: address,
        _from: address,
        _to: address,
        _value: uint256,
        _data: bytes32,
        _operatorData: bytes32
    ) -> bool: view

# @dev Emitted when `_value` tokens are moved from one account (`from`)
#      to another (`to`).
# @dev Note that `_value` may be zero.
event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256
# @dev Emitted when the allowance of a `_spender` for an `_owner` is set by
#      a call to {approve}. `_value` is the new allowance.
event Approval:
    _owner: indexed(address)
    _spender: indexed(address)
    _value: uint256 
# @dev TODO
event Sent:
    _operator: indexed(address)
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256
    _data: bytes32
    _operatorData: bytes32
# @dev TODO
event Minted:
    _operator: indexed(address)
    _to: indexed(address)
    _value: uint256
    _data: bytes32
    _operatorData: bytes32
# @dev TODO
event Burned:
    _operator: indexed(address)
    _from: indexed(address)
    _value: uint256
    _data: bytes32
    _operatorData: bytes32
# @dev TODO
event AuthorizedOperator:
    _operator: indexed(address)
    _owner: indexed(address)
# @dev TODO
event RevokedOperator:
    _operator: indexed(address)
    _owner: indexed(address)

# @dev Name of the token.
name: public(String[64])
# @dev Symbol of the token, usually a shorter version of the name.
symbol: public(String[32])
# @dev Amount of tokens in existence.
totalSupply: public(uint256)
# @dev Returns the smallest part of the token that is not divisible. This
#      means all token operations (creation, movement and destruction) must have
#      amounts that are a multiple of this number.
granularity: constant(uint256) = 1
# @dev Always return `18`, as per EIP-777 
decimals: constant(uint256) = 18

# @dev By declaring `balanceOf` as public, vyper automatically generates a 'balanceOf()' getter
#      method to allow access to account balances.
# @dev The _KeyType will become a required parameter for the getter and it will return _ValueType.
# @dev See: https://vyper.readthedocs.io/en/v0.1.0-beta.8/types.html?highlight=getter#mappings
balanceOf: public(HashMap(address, uint256))

# @dev ERC20-allowances
allowances: HashMap(address, HashMap(address, uint256))

operators: HashMap(address, HashMap(address, bool))

defaultOperators: HashMap(address, bool))
# defaultOperatorsArray: address[] # TODO: how to declare an array of addresses?
revokedDefaultOperators: HashMap(address, HashMap(address, bool))

# @dev Mapping of interface id to bool about whether or not it's supported
supportedInterfaces: public(HashMap(bytes32, bool))


@external
def __init__(_name: String[64], _symbol: String[32]): # TODO: add defaultOperators
    # Register interfaces
    self.supportedInterfaces[keccak256("ERC777TokensSender")] = True
    self.supportedInterfaces[keccak256("ERC777TokensRecipient")] = True
    self.name = _name
    self.symbol = symbol


@view
@external
def allowance(_owner : address, _spender : address) -> uint256:
    """
    @dev Function to check the amount of tokens that an _owner allowed to a _spender.
    @param _owner The address which owns the tokens.
    @param _spender The address which will spend the tokens.
    @return An uint256 specifying the amount of tokens still available for the _spender.
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
    _owner: address = msg.sender
    self._approve(_owner, _spender, _value)
    return True


@external
def burn(_value: uint256, _data: bytes32) -> bool:
    """
    @dev Burn an amount (`_value`) of the token of msg.sender.
    @param _value Quantity of token burned.
    @param _data Extra information provided (if any).
    @return True if burn succeeded, False otherwise.
    """
    return self._burn(msg.sender, _value, _data, '')


# TODO: is `send` a key-word?  ERC777.sol has a `_send` AND a `send` function.
@internal
def send(_to: address, _value: uint256, _data: bytes32):
    """
    @dev Send `_value` tokens from msg.sender to another address(`to`)
    @param _from Token _owner address.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient
    """
    _from: address = msg.sender

    self._send(_from, _to, _value, '', True)


@external
def transfer(_to: address, _value: uint256) -> bool:
    """
    @dev Moves `_value` tokens from the caller's account to `_to`.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @return True if transfer succeeded, False otherwise.
    """
    assert _to != ZERO_ADDRESS
    _from: address = msg.sender
    
    self._callTokensToSend(_from, _from, _to, _value, '', '')
    self._move(_from, _from, _to, _value, '', '')
    self._callTokensReceived(_from, _from, _to, _value, '', '', False)
    return True


@external
def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
    """
    @dev Moves `_value` tokens from `sender` to `_to` using the allowance mechanism.
    @param _from Address to receive tokens.
    @param _to Address to receive tokens.
    @param _value Quantity of token transferred.
    @return True if transfer succeeded, False otherwise.
    """
    assert _to != ZERO_ADDRESS
    assert _from != ZERO_ADDRESS
    _operator: address = msg.sender

    self._callTokensToSend(_operator, _from, _to, _value, '', '')
    self._move(_operator, _from, _to, _value, '', '')
    self._approve(_from, _operator, self.allowances[_from][_operator] - _value)
    self._callTokensReceived(_operator, _from, _to, _value, '', '', False)
    return True

######################z
# _OPERATOR functions #
######################
 
@external
def isOperatorFor(_operator: address, _owner: address) -> bool:
    """
    @dev Check if an address (`_operator`) can control the tokens held by an address (`_owner`).
    @param _operator The address which controls the tokens.
    @param _owner The address which holds the tokens.
    @return bool
    """
    return _operator == _owner or \
        self.operators[_owner][_operator] or \
        (self.defaultOperators[_operator] and \
        self.revokedDefaultOperators[_owner][_operator])


@external
def authorizeOperator(_operator: address):
    """
    @dev Make an account an _operator of the caller.
    @param _operator The address to control tokens.
    """
    assert isOperatorFor(_operator, msg.sender)

    if self.defaultOperators[_operator]:
        empty(self.revokedDefaultOperators[msg.sender][_operator])
    else:
        self.operators[msg.sender][_operator] = True

    log AuthorizedOperator(_operator, msg.sender)


@external
def revokeOperator(_operator: address):
    """
    @dev Revoke an account's _operator status for the caller.
    @param _operator The address to lose _operator status.
    """
    assert _operator != msg.sender

    if self.defaultOperators[_operator]:
        self.revokedDefaultOperators[msg.sender][_operator] = True
    else:
        empty(self.operators[msg.sender][_operator])

    log RevokedOperator(_operator, msg.sender)


@view
@external
def defaultOperators():
    return self.defaultOperatorsArray # TODO: `defaultOperatorsArray`


@external
def operatorSend(_from: address, _to: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    """
    @dev Moves `_value` of tokens from `_from` to `_to`.
    @dev The caller must be an _operator of `_from`.
    @param _from Address to send tokens.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    """
    assert self.isOperatorFor(msg.sender, _from)
    return self._send(_from, _to, _value, _data, _operatorData, True)


@external
def operatorBurn(_from: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    """
    @dev Destroys `_value` tokens from `_from`, reducing the total supply.
    @dev If a send hook is registered for `_from`, the corresponding function will
         be called with `_data` and `_operatorData`.
    @param _from Address to burn tokens from.
    @param _value Quantity of token burned.
    @param _data Extra information provided (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    """
    assert self.isOperatorFor(msg.sender, _from)
    return self._burn(_from, _value, _data, _operatorData)


######################
# INTERNAL functions #
######################
@internal
def _approve(_owner: address, _spender: address, _value: uint256):
    """
    @dev    Approve the passed address to spend the specified amount of tokens on behalf of msg.sender.
    @param _owner The address which owns the tokens.
    @param _spender The address which will spend the tokens.
    @param _value Quantity of tokens to be spent.
    """
    assert _owner != ZERO_ADDRESS
    assert _spender != ZERO_ADDRESS
    self.allowances[_owner][_spender] = _value
    log Approval(_owner, _spender, _value)


@internal
def _burn(_from: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    """
    @dev Burn `_value` tokens from address `_from`.
    @param _from Token _owner address.
    @param _value Quantity of tokens burned.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    """
    assert _from != ZERO_ADDRESS
    _operator: address = msg.sender
    
    self._beforeTokenTransfer(_operator, _from, ZERO_ADDRESS, _value)
    self._callTokensToSend(_operator, _from, ZERO_ADDRESS, _value, _data, _operatorData)
    self.totalSupply -= _value
    self.balanceOf[_from] -= _value
    log Burned(_operator, _from, _value, _data, _operatorData)
    log Transfer(_from, ZERO_ADDRESS, _value)


@internal
def _mint(_to: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    """
    @dev Creates `_value` tokens and assigns them to `_to`, increasing the total supply.
    @param _to Address to receive tokens.
    @param _value Quantity of token minted.
    @param _data Extra information provided for the recipient (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    @return True if mint succeeded, False otherwise.
    """
    assert _to != ZERO_ADDRESS
    _operator: address = msg.sender

    self._beforeTokenTransfer(_operator, ZERO_ADDRESS, _to, _value)
    self._callTokensToSend(_operator, _from, ZERO_ADDRESS, _value, _data, _operatorData)
    self.totalSupply += _value
    self.balanceOf[_to] += _value
    self._callTokensReceived(_operator, ZERO_ADDRESS, _to, _value, _data, _operatorData, True)
    log Minted(_operator, _to, _value, _data, _operatorData)
    log Transfer(ZERO_ADDRESS, _to, _value)

@internal
def _move(_operator: address, _from: address, _to: address, _value: uint256, userData: bytes32, _operatorData: bytes32):
    _beforeTokenTransfer(_operator, _from, _to, _value)
    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value
    log Sent(_operator, _from, _to, _value, userData, _operatorData)
    log Transfer(_from, _to, _value)


@internal
def _send(_from: address, _to: address, _value: uint256, _data: bytes32, _operatorData: bytes32, requireReceptionAck: bool):
    """
    @dev Send `_value` tokens from one address(`_from`) to another address(`to`)
    @param _from Token _owner address.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient
    """
    assert _from != ZERO_ADDRESS
    assert _to != ZERO_ADDRESS
    _operator: address = msg.sender
    
    self._callTokensToSend(_operator, _from, _to, _value, _data, _operatorData)
    self._move(_operator, _from, _to, _value, _data, _operatorData)
    self._callTokensReceived(_operator, _from, _to, _value, _data, _operatorData, requireReceptionAck)


@internal
def _callTokensToSend(_operator: address, _from: address, _to: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    """
    @dev Send `_value` tokens from one address(`_from`) to another address(`to`).
    @param _operator Token _operator address.
    @param _from Address to send tokens.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    """
    implementer: address = _ERC1820_REGISTRY.getInterfaceImplementer(_from, keccak256("ERC777TokensSender"))
    if implementer != ZERO_ADDRESS:
        ERC777Sender(implementer).tokenstoSend(_operator, _from, _to, _value, _data, _operatorData)


@internal
def _callTokensReceived(_operator: address, _from: address, _to: address, _value: uint256, _data: bytes32, _operatorData: bytes32, requireReceptionAck: bool):
    """
    @dev Send `_value` tokens from one address(`_from`) to another address(`to`).
    @param _operator Token _operator address.
    @param _from Address to send tokens.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient
    """
    implementer: address = _ERC1820_REGISTRY.getInterfaceImplementer(_to, keccak256("ERC777TokensRecipient"))
    if implementer != ZERO_ADDRESS:
        ERC777Recipient(implementer).tokensReceived(_operator, _from, _to, _value, _data, _operatorData)
    elif requireReceptionAck:
        assert not _to.is_contract()


@internal
def _beforeTokenTransfer(_operator: address, _from: address, _to: address, _value: uint256):
    pass

# @title Implementation of ERC-777 token standard.
# @author Carl Farterson (@carlfarterson)
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-777.md

from vyper.interfaces import ERC777

implements: ERC777


# @dev Interface of the global ERC1820 Registry, as defined in the
#      https://eips.ethereum.org/EIPS/eip-1820[EIP]. Accounts may register
#      implementers for interfaces in this registry, as well as query support. 
interface ERC1820Registry:
    def setManager(_address: address, _newManager: address): nonpayable
    def getManager(_address: address) -> address: view
    def setInterfaceImplementer(_address: address, _interfaceHash: bytes32, _implementer: address): nonpayable
    def getInterfaceImplementer(_address: address, _interfaceHash: bytes32) -> address: view
    # TODO: default length of string?
    def interfaceHash(_interfaceName: String[128]) -> bytes32: nonpayable
    def updateERC165Cache(_interfaceName: String[128]): nonpayable
    def implementsERC165Interface(_address: address, _interfaceId: Bytes[4]) -> bool: view
    def implementsERC165InterfaceNoCache(_address: address, _interfaceId: Bytes[4]) -> bool: view
    event InterfaceImplementerSet:
        _address: indexed(address)
        _interfaceHash: bytes32
        _implementer: indexed(address)
    event ManagerChanged:
        _address: indexed(address)
        _newManager: indexed(address)

# @dev Interface of the ERC777TokensRecipient standard as defined in the EIP.
# @dev Accounts can be notified of tokens being sent to them by having a
#      contract implement this interface (contract holders can be their own
#      implementer) and registering it on the 
#      https://eips.ethereum.org/EIPS/eip-1820[ERC1820_global_registry].
interface ERC777Recipient:
    def tokensReceived(
        _operator: address,
        _from: address,
        _to: address,
        _value: uint256,
        _data: bytes32,
        _operatorData: bytes32
    ) -> bool: view

# @dev Interface of the ERC777TokensSender standard as defined in the EIP.
# @dev Token holders can be notified of operations performed on their tokens
#      by having a contract implement this interface (contract holders can be
#      their own implementer) and registering it on the 
#      https://eips.ethereum.org/EIPS/eip-1820[ERC1820 global registry].
interface ERC777Sender:
    def tokensToSend(
        _operator: address,
        _from: address,
        _to: address,
        _value: uint256,
        _data: bytes32,
        _operatorData: bytes32
    ) -> bool: view


event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256

event Approval:
    _owner: indexed(address)
    _spender: indexed(address)
    _value: uint256 

event Sent:
    _operator: indexed(address)
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256
    _data: bytes32
    _operatorData: bytes32

event Minted:
    _operator: indexed(address)
    _to: indexed(address)
    _value: uint256
    _data: bytes32
    _operatorData: bytes32

event Burned:
    _operator: indexed(address)
    _from: indexed(address)
    _value: uint256
    _data: bytes32
    _operatorData: bytes32

event AuthorizedOperator:
    _operator: indexed(address)
    _owner: indexed(address)

event RevokedOperator:
    _operator: indexed(address)
    _owner: indexed(address)


erc1820Registry: ERC1820Registry
erc1820RegistryAddress: constant(address) = 0x1820a4B7618BdE71Dce8cdc73aAB6C95905faD24

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

# @dev Always return `18`, as per EIP-777.
decimals: constant(uint256) = 18

# @dev Mapping of the amount of tokens owned by each account.
balanceOf: public(HashMap(address, uint256))

# @dev ERC20-allowances.
allowances: HashMap(address, HashMap(address, uint256))

# @dev For each account, a mapping of its operators.
operators: HashMap(address, HashMap(address, bool))

# @dev For each account, a mapping of its revoked default operators.
revokedDefaultOperators: HashMap(address, HashMap(address, bool))

# @dev Immutable, but accounts may revoke them (tracked in revokedDefaultOperators).
defaultOperators: HashMap(address, bool))

# @dev This isn't ever read from - it's only used to respond to the defaultOperators query.
defaultOperatorsArray: address[4]

# @dev Mapping of interface id to bool about whether or not it's supported.
supportedInterfaces: public(HashMap(bytes32, bool))


@external
def __init__(_name: String[64], _symbol: String[32], _defaultOperators: address[4]):
    self.name = _name
    self.symbol = symbol
    for i in range(len(_defaultOperators)):
        self.defaultOperators[defaultOperatorsArray[i]] = True
    # Register interfaces
    self.erc1820Registry = erc1820Registry(erc1820RegistryAddress)
    self.erc1820Registry.setInterfaceImplementer(self, keccak256("ERC777TokenSender"), self)
    self.erc1820Registry.setInterfaceImplementer(self, keccak256("ERC777TokensRecipient"), self)

######################
#  PUBLIC functions  #
######################
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
    return self._burn(msg.sender, _value, _data, b'')


@internal
def send(_to: address, _value: uint256, _data: bytes32):
    """
    @dev Send `_value` tokens from msg.sender to another address(`to`).
    @param _from Token _owner address.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient.
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
    
    self._callTokensToSend(_from, _from, _to, _value, b'', b'')
    self._move(_from, _from, _to, _value, b'', b'')
    self._callTokensReceived(_from, _from, _to, _value, b'', b'', False)
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

    self._callTokensToSend(_operator, _from, _to, _value, b'', b'')
    self._move(_operator, _from, _to, _value, b'', b'')
    self._approve(_from, _operator, self.allowances[_from][_operator] - _value)
    self._callTokensReceived(_operator, _from, _to, _value, b'', b'', False)
    return True

######################
# OPERATOR functions #
######################
@view
@external
def defaultOperators():
    return self.defaultOperatorsArray


@external
def isOperatorFor(_operator: address, _owner: address) -> bool:
    """
    @dev Check if an address (`_operator`) can control the tokens held by an address (`_owner`).
    @param _operator The address which controls the tokens.
    @param _owner The address which holds the tokens.
    @return bool
    """
    return _operator == _owner or \
        (self.defaultOperators[_operator] and self.revokedDefaultOperators[_owner][_operator]) or \
        self.operators[_owner][_operator]


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
    @dev Send `_value` tokens from one address(`_from`) to another address(`to`).
    @param _from Token _owner address.
    @param _to Address to receive tokens.
    @param _value Quantity of token sent.
    @param _data Extra information provided by the token _owner (if any).
    @param _operatorData Extra information provided by the _operator (if any).
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient.
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
    implementer: address = self.erc1820Registry.getInterfaceImplementer(_from, keccak256("ERC777TokensSender"))
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
    @param requireReceptionAck if true, contract recipients are required to implement ERC777TokensRecipient.
    """
    implementer: address = self.erc1820Registry.getInterfaceImplementer(_to, keccak256("ERC777TokensRecipient"))
    if implementer != ZERO_ADDRESS:
        ERC777Recipient(implementer).tokensReceived(_operator, _from, _to, _value, _data, _operatorData)
    elif requireReceptionAck:
        assert not _to.is_contract()


@internal
def _beforeTokenTransfer(_operator: address, _from: address, _to: address, _value: uint256):
    pass

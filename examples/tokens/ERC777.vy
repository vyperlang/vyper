# @dev Implementation of ERC-777 token standard.
# @author Carl Farterson (@carlfarterson)
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-777.md

# from vyper.interfaces import ERC777

# implements: ERC777
event Transfer:
    sender: indexed(address)
    reciver: indexed(address)
    value: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Sent:
    operator: indexed(address)
    sender: indexed(address)
    receiver: indexed(address)
    amount: uint256
    data: bytes32
    operatorData: bytes32

event Minted:
    operator: indexed(address)
    receiver: indexed(address)
    amount: uint256
    data: bytes32
    operatorData: bytes32

event Burned:
    operator: indexed(address)
    sender: indexed(address)
    amount: uint256
    data: bytes32
    operatorData: bytes32

event AuthorizedOperator:
    operator: indexed(address)
    tokenHolder: indexed(address)

event RevokedOperator:
    operator: indexed(address)
    tokenHolder: indexed(address)

_name: String[64]
_symbol: String[32]
_totalSupply: uint256
granularity: uint256 = 1
decimals: uint256 = 18

_balances: HashMap[address, uint256]

_defaultOperatorsArray: address[] # TODO: how to declare an array of addresses?

_defaultOperators: HashMap[address, bool]

_operators: HashMap[address, HashMap[address, bool]]
_revokedDefaultOperators: HashMap[address, HashMap[address, bool]]

### @dev ERC20-allowances
_allowances: HashMap[address, HashMap[address, uint256]]

# @dev Mapping of interface id to bool about whether or not it's supported
supportedInterfaces: HashMap[bytes32, bool]

### @dev keccak256("ERC777TokensSender")
_TOKENS_SENDER_INTERFACE_HASH: bytes32 = 0x29ddb589b1fb5fc7cf394961c1adf5f8c6454761adf795e67fe149f658abe895
### @dev keccak256("ERC777TokensRecipient")
_TOKENS_RECIPIENT_INTERFACE_HASH: bytes32 = 0xb281fc8c12954d22544db45de3159a39272895b169a852b314f9cc762e44c53b
# TODO: register interfaces ^

@external
def __init__(_name: String[64], _symbol: String[32]): # TODO: add defaultOperators
    self.name = _name
    self.symbol = _symbol

@external
def name() -> bytes32:
    ### @dev See {IERC777-name}.
    return self._name

@external
def symbol() -> bytes32:
    ### @dev See {IERC777-symbol}.
    return self._symbol

@external
def decimals() -> uint256:
    ### @dev See {IERC777-decimals}. Always returns `18`. 
    return 18;

@external
def granularity() -> uint256:
    ### @dev See {IERC777-granularity}. Always returns `1`.
    return 1

@external
def totalSupply() -> uint256:
    ### @dev See {IERC777-totalSupply}.
    return _totalSupply

@external
def balanceOf(tokenHolder: address) -> uint256:
    """
    @dev Returns the amount of tokens owned by an account (`tokenHolder`).
    @param tokenHolder ...
    @returns uint256
    """ 

    return _balances[tokenHolder]

@external
def transfer(recipient: address, amount: uint256) -> bool:
    """
    @dev See {IERC20-transfer}.
    @param recipient ...
    @param amount ...
    @returns bool
    """
    assert recipient != ZERO_ADDRESS
    _from: address = msg.sender
    _callTokensToSend(_from, _from, recipient, amount, '', '')
    _move(_from, _from, recipient, amount, '', '')
    _callTokensReceived(_from, _from, recipient, amount, '', '', False)
    return True

@external
def burn(amount: uint256, data: bytes32) -> bool:
    """
    @dev ...
    @param amount ...
    @param data ...
    @returns bool
    """
    return _burn(msg.sender, amount, data, '')

@external
def isOperatorFor(operator: address, tokenHolder: address) -> bool:
    """
    @dev ...
    @param operator
    @param tokenHolder
    @returns bool
    """
    return operator == tokenHolder ||
        _operators[tokenHolder][operator] ||
        _defaultOperators[operator] and _revokedDefaultOperators[tokenHolder][operator]

@external
def authorizeOperator(operator: address):
    """
    @dev ...
    @param operator ...
    """
    assert msg.sender == operator
    if _defaultOperators[operator]:
        delete _revokedDefaultOperators[msg.sender][operator] # TODO: `delete`
    else:
        _operators[msg.sender][operator] = True

    log AuthorizedOperator(operator, msg.sender)

@external
def revokeOperator(operator: address):
    """
    @dev ...
    @param operator ...
    """
    assert operator == msg.sender
    if _defaultOperators[operator]:
        _revokedDefaultOperators[msg.sender][operator] = True
    else:
        delete _operators[msg.sender][operator] # TODO: `delete`

    log RevokedOperator(operator, msg.sender)

@external
def defaultOperators() -> address[]:  # TODO: how do  you signify returning an array of addresses?
    return _defaultOperatorsArray

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
    assert isOperatorFor(msg.sender, sender)
    _send(sender, recipient, amount, data, operatorData, True)

@external
def operatorBurn(account: address, amount: uint256, data: bytes32, operatorData: bytes32):
    """
    @dev ...
    @param account ...
    @param amount ...
    @param data ...
    @param operatorData ...
    """
    assert isOperatorFor(msg.sender, account)
    _burn(account, amount, data, operatorData)

@external
def allowance(holder: address, spender: address) -> uint256:
    """
    @dev ...
    @param holder ...
    @param spender ...
    @returns uint256
    """
    return _allowances[holder][spender]

@external
def approve(spender: address, value: uint256) -> bool:
    """
    @dev ...
    @param spender ...
    @param value ...
    @returns bool
    """
    holder: address = msg.sender
    _approve(holder, spender, value)
    return True

@external
# NOTE: could broken erc20's without a `assert holder != ZERO_ADDRESS`
#   withdraw past tokens sent to `ZERO_ADDRESS`
def transferFrom(holder: address, recipient: address, amount: uint256) -> bool:
    """
    @dev ...
    @param holder ...
    @param recipient ...
    @param amount ...
    @returns bool
    """
    assert recipient != ZERO_ADDRESS
    assert holder != ZERO_ADDRESS
    spender: address = msg.sender
    _callTokensToSend(spender, holder, recipient, amount, '', '')
    _move(spender, holder, recipient, amount, '', '')
    assert _allowances[holder][spender] - amount > 0
    _approve(holder, spender, _allowances[holder][spender] - amount)
    _callTokensReceived(spender, holder, recipient, amount, '', '', False)
    return True

def _mint(account: address, amount: uint256, userData: bytes32, operatorData: bytes32) -> bool:
    """
    @dev ...
    @param account ...
    @param amount ...
    @param userData ...
    @param operatorData ...
    @returns bool
    """
    assert account != ZERO_ADDRESS
    operator: address = msg.sender
    _beforeTokenTransfer(operator, ZERO_ADDRESS, account, amount)
    _totalSupply += amount
    _balances[account] += amount
    _callTokensReceived(operator, ZERO_ADDRESS, account, amount, userData, operatorData, True)
    log Minted(operator, account, amount, userData, operatorData)
    log Transfer(ZERO_ADDRESS, account, amount)

# TODO: is `send` a key-word? 
def _send(_from: address, to: address, amount: uint256, userData: bytes32, operatorData: bytes32, requireReceptionAck: bool):
    """
    @dev ...
    @param _from ...
    @param to ...
    @param amount ...
    @param userData ...
    @param operatorData ...
    @param requireReceptionAck ...
    """
    assert _from != ZERO_ADDRESS
    assert to != ZERO_ADDRESS
    operator: address = msg.sender
    _callTokensToSend(operator, _from, to, amount, userData, operatorData)
    _move(operator, _from, to, amount, userData, operatorData)
    _callTokensReceived(operator, _from, to, amount, userData, operatorData, requireReceptionAck)

def _burn(_from: address, amount: uint256, data: bytes32, operatorData: bytes32):
    assert account != ZERO_ADDRESS
    operator: address = msg.sender
    _beforeTokenTransfer(operator, _from, ZERO_ADDRESS, amount)
    _callTokensToSend(operator, _from, ZERO_ADDRESS, amount, userData, operatorData)
    assert _balances[_from] - amount > 0
    _totalSupply -= amount
    _balances[account] -= amount
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
    assert _balances[_from] - amount > 0
    _balances[_from] -= amount
    _balances[to] += amount
    log Sent(operator, _from, to, amount, userData, operatorData)
    log Transfer(_from, to, amount)

def _approve(holder: address, spender: address, value: uint256):
    assert holder != ZERO_ADDRESS
     assert sender != ZERO_ADDRESS
     _allowances[holder][spender] = value
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
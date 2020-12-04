interface_code = """
# Events
event Sent:
    operator: indexed(address)
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256
    data: bytes32
    operatorData: bytes32

event Minted:
    operator: indexed(address)
    _to: indexed(address)
    _value: uint256
    data: bytes32
    operatorData: bytes32

event Burned:
    operator: indexed(address)
    _from: indexed(address)
    _value: uint256
    data: bytes32
    operatorData: bytes32

event AuthorizedOperator:
    operator: indexed(address)
    owner: indexed(address)

event RevokedOperator:
    operator: indexed(address)
    owner: indexed(address)

# Functions
@view
@external
def name() -> string[32]:
    pass

@view
@external
def symbol() -> string[32]:
    pass

@view
@external
def granularity() -> uint256:
    pass

@view
@external
def totalSupply() -> uint256:
    pass

@view
@external
def balanceOf(_owner: address) -> uint256:
    pass

@external
# TODO: how to handle `send` keyword?
def _send(_from: address, _to: address, _value: uint256, data: bytes32, operatorData: bytes32, requireReceptionAck: bool):
    pass

@external
def burn(_value: uint256, data: bytes32) -> bool:
    pass

@external
@view
def isOperatorFor(operator: address, owner: address) -> bool:
    pass

@external
def authorizeOperator(operator: address):
    pass

@external
def revokeOperator(operator: address):
    pass

@external
@view 
def defaultOperators() -> []: # TODO: how to return array of addresses?
    pass

@external
def operatorSend(_from: address, _to: address, _value: uint256, data: bytes32, operatorData: bytes32):
    pass

@external
def operatorBurn(_from: address, _value: uint256, data: bytes32, operatorData: bytes32):
    pass
"""
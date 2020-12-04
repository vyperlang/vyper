interface_code = """
# Events
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
def _send(_from: address, _to: address, _value: uint256, _data: bytes32, _operatorData: bytes32, requireReceptionAck: bool):
    pass

@external
def burn(_value: uint256, _data: bytes32) -> bool:
    pass

@external
@view
def isOperatorFor(_operator: address, _owner: address) -> bool:
    pass

@external
def authorizeOperator(_operator: address):
    pass

@external
def revokeOperator(_operator: address):
    pass

@external
@view 
def defaultOperators() -> []: # TODO: how to return array of addresses?
    pass

@external
def operatorSend(_from: address, _to: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    pass

@external
def operatorBurn(_from: address, _value: uint256, _data: bytes32, _operatorData: bytes32):
    pass
"""
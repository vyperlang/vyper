interface_code = """
# Events
event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256

event Approval:
    _owner: indexed(address)
    _spender: indexed(address)
    _value: uint256

# Functions
@view
@public
def totalSupply() -> uint256:
    pass

@view
@public
def balanceOf(_owner: address) -> uint256:
    pass

@view
@public
def allowance(_owner: address, _spender: address) -> uint256:
    pass

@public
def transfer(_to: address, _value: uint256) -> bool:
    pass

@public
def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
    pass

@public
def approve(_spender: address, _value: uint256) -> bool:
    pass
"""

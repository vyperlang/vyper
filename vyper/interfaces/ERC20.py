interface_code = """
# Events
Transfer: event({_from: address, _to: address, _value: uint256})
Approval: event({_owner: address, _spender: address, _value: uint256})

# Functions
@constant
@public
def totalSupply() -> uint256:
    pass

@constant
@public
def balanceOf(_owner: address) -> uint256:
    pass

@constant
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

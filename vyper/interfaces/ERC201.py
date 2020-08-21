interface_code = """
# Events
event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256

# Functions
@view
@external
def totalSupply() -> uint256:
    pass

@view
@external
def balanceOf(_owner: address) -> uint256:
    pass

@external
def transfer(_to: address, _value: uint256) -> bool:
    pass
"""

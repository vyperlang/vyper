# pragma version >0.3.10

"""
@title To avoid naming conflicts between ERC20 and ERC721 events, we need to first deploy an IERC20Event contract.
@author 0x77
"""


event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256


@external
def approve_event(_owner: address, _spender: address, _value: uint256) -> bool:
    log Approval(_owner, _spender, _value)
    return True


@external
def transfer_event(_sender: address, _receiver: address, _value: uint256) -> bool:
    log Approval(_sender, _receiver, _value)
    return True
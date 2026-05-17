# pragma version >=0.4.2
"""
@title Vault
@author CurveFi
@notice Holds the chain native asset and IERC20s
@license MIT
@custom:version 1.0.0
"""

version: public(constant(String[8])) = "1.0.0"


from ethereum.ercs import IERC20


event CommitOwnership:
    future_owner: address

event ApplyOwnership:
    owner: address


NATIVE: constant(address) = 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE


owner: public(address)
future_owner: public(address)

deployer: immutable(address)


@deploy
def __init__(_owner: address):
    self.owner = _owner

    log ApplyOwnership(owner=_owner)

    deployer = msg.sender


@external
def set_owner(_owner: address):

    assert msg.sender == deployer
    assert self.owner == deployer
    assert _owner != deployer

    self.owner = _owner
    log CommitOwnership(future_owner=_owner)
    log ApplyOwnership(owner=_owner)


@external
def transfer(_token: address, _to: address, _value: uint256):
    """
    @notice Transfer an asset
    @param _token The token to transfer, or NATIVE if transferring the chain native asset
    @param _to The destination of the asset
    @param _value The amount of the asset to transfer
    """
    assert msg.sender == self.owner

    if _token == NATIVE:
        send(_to, _value)
    else:
        assert extcall IERC20(_token).transfer(_to, _value, default_return_value=True)


@external
def commit_future_owner(_future_owner: address):
    assert msg.sender == self.owner

    self.future_owner = _future_owner
    log CommitOwnership(future_owner=_future_owner)


@external
def apply_future_owner():
    assert msg.sender == self.owner

    future_owner: address = self.future_owner
    self.owner = future_owner

    log ApplyOwnership(owner=future_owner)


@payable
@external
def __default__():
    assert len(msg.data) == 0

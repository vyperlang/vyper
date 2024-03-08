#pragma version >0.3.10

from ethereum.ercs import IERC20


interface Factory:
    def register(): nonpayable


token: public(IERC20)
factory: Factory


@deploy
def __init__(_token: IERC20, _factory: Factory):
    self.token = _token
    self.factory = _factory


@external
def initialize():
    # Anyone can safely call this function because of EXTCODEHASH
    extcall self.factory.register()


# NOTE: This contract restricts trading to only be done by the factory.
#       A practical implementation would probably want counter-pairs
#       and liquidity management features for each exchange pool.


@external
def receive(_from: address, _amt: uint256):
    assert msg.sender == self.factory.address
    success: bool = extcall self.token.transferFrom(_from, self, _amt)
    assert success


@external
def transfer(_to: address, _amt: uint256):
    assert msg.sender == self.factory.address
    success: bool = extcall self.token.transfer(_to, _amt)
    assert success

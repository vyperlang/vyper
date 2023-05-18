from vyper.interfaces import ERC20


interface Factory:
    def register(): nonpayable


token: public(ERC20)
factory: Factory


@external
def __init__(_token: ERC20, _factory: Factory):
    self.token = _token
    self.factory = _factory


@external
def initialize():
    # Anyone can safely call this function because of EXTCODEHASH
    self.factory.register()


# NOTE: This contract restricts trading to only be done by the factory.
#       A practical implementation would probably want counter-pairs
#       and liquidity management features for each exchange pool.


@external
def receive(_from: address, _amt: uint256):
    assert msg.sender == self.factory.address
    success: bool = self.token.transferFrom(_from, self, _amt)
    assert success


@external
def transfer(_to: address, _amt: uint256):
    assert msg.sender == self.factory.address
    success: bool = self.token.transfer(_to, _amt)
    assert success

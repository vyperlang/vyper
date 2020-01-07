from vyper.interfaces import ERC20


contract Factory:
    def register(): modifying


token: public(address)
factory: address


@public
def __init__(_token: address, _factory: address):
    self.token = _token
    self.factory = _factory


@public
def initialize():
    # Anyone can safely call this function because of EXTCODEHASH
    Factory(self.factory).register()


# NOTE: This contract restricts trading to only be done by the factory.
#       A practical implementation would probably want counter-pairs
#       and liquidity management features for each exchange pool.


@public
def receive(_from: address, _amt: uint256):
    assert msg.sender == self.factory
    success: bool = ERC20(self.token).transferFrom(_from, self, _amt)
    assert success


@public
def transfer(_to: address, _amt: uint256):
    assert msg.sender == self.factory
    success: bool = ERC20(self.token).transfer(_to, _amt)
    assert success

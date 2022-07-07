from vyper.interfaces import ERC20


interface Factory:
    def register(): nonpayable


token: public(ERC20)
factory: Factory


@external
def __init__(token: ERC20, factory: Factory):
    self.token = token
    self.factory = factory


@external
def initialize():
    # Anyone can safely call this function because of EXTCODEHASH
    self.factory.register()


# NOTE: This contract restricts trading to only be done by the factory.
#       A practical implementation would probably want counter-pairs
#       and liquidity management features for each exchange pool.


@external
def receive(sender: address, amount: uint256):
    assert msg.sender == self.factory.address
    success: bool = self.token.transferFrom(sender, self, amount)
    assert success


@external
def transfer(receiver: address, amount: uint256):
    assert msg.sender == self.factory.address
    success: bool = self.token.transfer(receiver, amount)
    assert success

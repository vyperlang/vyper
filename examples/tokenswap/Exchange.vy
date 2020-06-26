from vyper.interfaces import ERC20


interface Registry:
    def register(): nonpayable


token: public(ERC20)
owner: public(Registry)


@external
def __init__(_token: address, _registry: address):
    self.token = ERC20(_token)
    self.owner = Registry(_registry)


@external
def initialize():
    # Anyone can safely call this function because of EXTCODEHASH
    # Registry can't call this contract until it is registered
    self.owner.register()


# NOTE: This contract restricts trading to only be done by the registry.
#       A practical implementation would probably want counter-pairs
#       and liquidity management features for each exchange pool.


@external
def receive(_from: address, _amt: uint256):
    assert msg.sender == self.owner.address  # Only the Reigstry may call this
    success: bool = self.token.transferFrom(_from, self, _amt)
    assert success


@external
def transfer(_to: address, _amt: uint256):
    assert msg.sender == self.owner.address  # Only the Reigstry may call this
    success: bool = self.token.transfer(_to, _amt)
    assert success

# NOTE: Add liquidity Deposit/Withdrawal logic

interface_code = """
# Events
event Deposit:
    sender: indexed(address)
    owner: indexed(address)
    assets: uint256
    shares: uint256

event Withdraw:
    sender: indexed(address)
    receiver: indexed(address)
    owner: indexed(address)
    assets: uint256
    shares: uint256

# Functions
@view
@external
def asset() -> address:
    pass

@view
@external
def totalAssets() -> uint256:
    pass

@view
@external
def convertToShares(assetAmount: uint256) -> uint256:
    pass

@view
@external
def convertToAssets(shareAmount: uint256) -> uint256:
    pass

@view
@external
def maxDeposit(owner: address) -> uint256:
    pass

@view
@external
def previewDeposit(assets: uint256) -> uint256:
    pass

@external
def deposit(assets: uint256, receiver: address=msg.sender) -> uint256:
    pass

@view
@external
def maxMint(owner: address) -> uint256:
    pass

@view
@external
def previewMint(shares: uint256) -> uint256:
    pass

@external
def mint(shares: uint256, receiver: address=msg.sender) -> uint256:
    pass

@view
@external
def maxWithdraw(owner: address) -> uint256:
    pass

@view
@external
def previewWithdraw(assets: uint256) -> uint256:
    pass

@external
def withdraw(assets: uint256, receiver: address=msg.sender, owner: address=msg.sender) -> uint256:
    pass

@view
@external
def maxRedeem(owner: address) -> uint256:
    pass

@view
@external
def previewRedeem(shares: uint256) -> uint256:
    pass

@external
def redeem(shares: uint256, receiver: address=msg.sender, owner: address=msg.sender) -> uint256:
    pass
"""

#pragma version >0.3.10

# NOTE: Copied from https://github.com/fubuloubu/ERC4626/blob/1a10b051928b11eeaad15d80397ed36603c2a49b/contracts/VyperVault.vy

# example implementation of an ERC4626 vault

###########################################################################
## THIS IS EXAMPLE CODE, NOT MEANT TO BE USED IN PRODUCTION! CAVEAT EMPTOR!
###########################################################################

from ethereum.ercs import IERC20
from ethereum.ercs import IERC4626

implements: IERC20
implements: IERC4626

##### ERC20 #####

totalSupply: public(uint256)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])

NAME: constant(String[10]) = "Test Vault"
SYMBOL: constant(String[5]) = "vTEST"
DECIMALS: constant(uint8) = 18

##### ERC4626 #####

asset: public(IERC20)


@deploy
def __init__(asset: IERC20):
    self.asset = asset


@view
@external
def name() -> String[10]:
    return NAME


@view
@external
def symbol() -> String[5]:
    return SYMBOL


@view
@external
def decimals() -> uint8:
    return DECIMALS


@external
def transfer(receiver: address, amount: uint256) -> bool:
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[receiver] += amount
    log IERC20.Transfer(msg.sender, receiver, amount)
    return True


@external
def approve(spender: address, amount: uint256) -> bool:
    self.allowance[msg.sender][spender] = amount
    log IERC20.Approval(msg.sender, spender, amount)
    return True


@external
def transferFrom(sender: address, receiver: address, amount: uint256) -> bool:
    self.allowance[sender][msg.sender] -= amount
    self.balanceOf[sender] -= amount
    self.balanceOf[receiver] += amount
    log IERC20.Transfer(sender, receiver, amount)
    return True


@view
@external
def totalAssets() -> uint256:
    return staticcall self.asset.balanceOf(self)


@view
@internal
def _convertToAssets(shareAmount: uint256) -> uint256:
    totalSupply: uint256 = self.totalSupply
    if totalSupply == 0:
        return 0

    # NOTE: `shareAmount = 0` is extremely rare case, not optimizing for it
    # NOTE: `totalAssets = 0` is extremely rare case, not optimizing for it
    return shareAmount * staticcall self.asset.balanceOf(self) // totalSupply


@view
@external
def convertToAssets(shareAmount: uint256) -> uint256:
    return self._convertToAssets(shareAmount)


@view
@internal
def _convertToShares(assetAmount: uint256) -> uint256:
    totalSupply: uint256 = self.totalSupply
    totalAssets: uint256 = staticcall self.asset.balanceOf(self)
    if totalAssets == 0 or totalSupply == 0:
        return assetAmount  # 1:1 price

    # NOTE: `assetAmount = 0` is extremely rare case, not optimizing for it
    return assetAmount * totalSupply // totalAssets


@view
@external
def convertToShares(assetAmount: uint256) -> uint256:
    return self._convertToShares(assetAmount)


@view
@external
def maxDeposit(owner: address) -> uint256:
    return max_value(uint256)


@view
@external
def previewDeposit(assets: uint256) -> uint256:
    return self._convertToShares(assets)


@external
def deposit(assets: uint256, receiver: address=msg.sender) -> uint256:
    shares: uint256 = self._convertToShares(assets)
    extcall self.asset.transferFrom(msg.sender, self, assets)

    self.totalSupply += shares
    self.balanceOf[receiver] += shares
    log IERC4626.Deposit(msg.sender, receiver, assets, shares)
    return shares


@view
@external
def maxMint(owner: address) -> uint256:
    return max_value(uint256)


@view
@external
def previewMint(shares: uint256) -> uint256:
    assets: uint256 = self._convertToAssets(shares)

    # NOTE: Vyper does lazy eval on `and`, so this avoids SLOADs most of the time
    if assets == 0 and staticcall self.asset.balanceOf(self) == 0:
        return shares  # NOTE: Assume 1:1 price if nothing deposited yet

    return assets


@external
def mint(shares: uint256, receiver: address=msg.sender) -> uint256:
    assets: uint256 = self._convertToAssets(shares)

    if assets == 0 and staticcall self.asset.balanceOf(self) == 0:
        assets = shares  # NOTE: Assume 1:1 price if nothing deposited yet

    extcall self.asset.transferFrom(msg.sender, self, assets)

    self.totalSupply += shares
    self.balanceOf[receiver] += shares
    log IERC4626.Deposit(msg.sender, receiver, assets, shares)
    return assets


@view
@external
def maxWithdraw(owner: address) -> uint256:
    return max_value(uint256)  # real max is `self.asset.balanceOf(self)`


@view
@external
def previewWithdraw(assets: uint256) -> uint256:
    shares: uint256 = self._convertToShares(assets)

    # NOTE: Vyper does lazy eval on and, so this avoids SLOADs most of the time
    if shares == assets and self.totalSupply == 0:
        return 0  # NOTE: Nothing to redeem

    return shares


@external
def withdraw(assets: uint256, receiver: address=msg.sender, owner: address=msg.sender) -> uint256:
    shares: uint256 = self._convertToShares(assets)

    # NOTE: Vyper does lazy eval on `and`, so this avoids SLOADs most of the time
    if shares == assets and self.totalSupply == 0:
        raise  # Nothing to redeem

    if owner != msg.sender:
        self.allowance[owner][msg.sender] -= shares

    self.totalSupply -= shares
    self.balanceOf[owner] -= shares

    extcall self.asset.transfer(receiver, assets)
    log IERC4626.Withdraw(msg.sender, receiver, owner, assets, shares)
    return shares


@view
@external
def maxRedeem(owner: address) -> uint256:
    return max_value(uint256)  # real max is `self.totalSupply`


@view
@external
def previewRedeem(shares: uint256) -> uint256:
    return self._convertToAssets(shares)


@external
def redeem(shares: uint256, receiver: address=msg.sender, owner: address=msg.sender) -> uint256:
    if owner != msg.sender:
        self.allowance[owner][msg.sender] -= shares

    assets: uint256 = self._convertToAssets(shares)
    self.totalSupply -= shares
    self.balanceOf[owner] -= shares

    extcall self.asset.transfer(receiver, assets)
    log IERC4626.Withdraw(msg.sender, receiver, owner, assets, shares)
    return assets


@external
def DEBUG_steal_tokens(amount: uint256):
    # NOTE: This is the primary method of mocking share price changes
    # do not put in production code!!!
    extcall self.asset.transfer(msg.sender, amount)

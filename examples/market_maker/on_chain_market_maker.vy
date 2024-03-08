#pragma version >0.3.10

from ethereum.ercs import IERC20


totalEthQty: public(uint256)
totalTokenQty: public(uint256)
# Constant set in `initiate` that's used to calculate
# the amount of ether/tokens that are exchanged
invariant: public(uint256)
token: IERC20
owner: public(address)

# Sets the on chain market maker with its owner, initial token quantity,
# and initial ether quantity
@external
@payable
def initiate(token_addr: address, token_quantity: uint256):
    assert self.invariant == 0
    self.token = IERC20(token_addr)
    extcall self.token.transferFrom(msg.sender, self, token_quantity)
    self.owner = msg.sender
    self.totalEthQty = msg.value
    self.totalTokenQty = token_quantity
    self.invariant = msg.value * token_quantity
    assert self.invariant > 0

# Sells ether to the contract in exchange for tokens (minus a fee)
@external
@payable
def ethToTokens():
    fee: uint256 = msg.value // 500
    eth_in_purchase: uint256 = msg.value - fee
    new_total_eth: uint256 = self.totalEthQty + eth_in_purchase
    new_total_tokens: uint256 = self.invariant // new_total_eth
    extcall self.token.transfer(msg.sender, self.totalTokenQty - new_total_tokens)
    self.totalEthQty = new_total_eth
    self.totalTokenQty = new_total_tokens

# Sells tokens to the contract in exchange for ether
@external
def tokensToEth(sell_quantity: uint256):
    extcall self.token.transferFrom(msg.sender, self, sell_quantity)
    new_total_tokens: uint256 = self.totalTokenQty + sell_quantity
    new_total_eth: uint256 = self.invariant // new_total_tokens
    eth_to_send: uint256 = self.totalEthQty - new_total_eth
    send(msg.sender, eth_to_send)
    self.totalEthQty = new_total_eth
    self.totalTokenQty = new_total_tokens

# Owner can withdraw their funds and destroy the market maker
@external
def ownerWithdraw():
    assert self.owner == msg.sender
    extcall self.token.transfer(self.owner, self.totalTokenQty)
    selfdestruct(self.owner)

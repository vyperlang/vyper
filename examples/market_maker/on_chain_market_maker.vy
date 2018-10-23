units: {
    currency_value: "a currency"
}

totalEthQty: public(wei_value)
totalTokenQty: public(uint256(currency_value))
# Constant set in `initiate` that's used to calculate
# the amount of ether/tokens that are exchanged
invariant: public(uint256(wei * currency_value))
tokenAddress: address(ERC20)
owner: public(address)

# Sets the on chain market maker with its owner, intial token quantity,
# and initial ether quantity
@public
@payable
def initiate(tokenAddr: address, tokenQuantity: uint256(currency_value)):
    assert self.invariant == 0
    self.tokenAddress = tokenAddr
    self.tokenAddress.transferFrom(msg.sender, self, as_unitless_number(tokenQuantity))
    self.owner = msg.sender
    self.totalEthQty = msg.value
    self.totalTokenQty = tokenQuantity
    self.invariant = msg.value * tokenQuantity
    assert self.invariant > 0

# Sells ether to the contract in exchange for tokens (minus a fee)
@public
@payable
def ethToTokens():
    fee: wei_value = msg.value / 500
    eth_in_purchase: wei_value = msg.value - fee
    newTotalEth: wei_value = self.totalEthQty + eth_in_purchase
    newTotalTokens: uint256(currency_value) = self.invariant / newTotalEth
    self.tokenAddress.transfer(msg.sender, as_unitless_number(self.totalTokenQty - newTotalTokens))
    self.totalEthQty = newTotalEth
    self.totalTokenQty = newTotalTokens

# Sells tokens to the contract in exchange for ether
@public
def tokensToEth(sellQuantity: uint256(currency_value)):
    self.tokenAddress.transferFrom(msg.sender, self, as_unitless_number(sellQuantity))
    newTotalTokens: uint256(currency_value) = self.totalTokenQty + sellQuantity
    newTotalEth: wei_value = self.invariant / newTotalTokens
    eth_to_send: wei_value = self.totalEthQty - newTotalEth
    send(msg.sender, eth_to_send)
    self.totalEthQty = newTotalEth
    self.totalTokenQty = newTotalTokens

# Owner can withdraw their funds and destroy the market maker
@public
def ownerWithdraw():
    assert self.owner == msg.sender
    self.tokenAddress.transfer(self.owner, as_unitless_number(self.totalTokenQty))
    selfdestruct(self.owner)

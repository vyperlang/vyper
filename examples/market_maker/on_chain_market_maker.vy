from vyper.interfaces import ERC20

units: {
    currency_value: "a currency"
}

totalEthQty: public(wei_value)
totalTokenQty: public(uint256(currency_value))
# Constant set in `initiate` that's used to calculate
# the amount of ether/tokens that are exchanged
invariant: public(uint256(wei * currency_value))
token_address: address(ERC20)
owner: public(address)

# Sets the on chain market maker with its owner, intial token quantity,
# and initial ether quantity
@public
@payable
def initiate(token_addr: address, token_quantity: uint256(currency_value)):
    assert self.invariant == 0
    self.token_address = token_addr
    self.token_address.transferFrom(msg.sender, self, as_unitless_number(token_quantity))
    self.owner = msg.sender
    self.totalEthQty = msg.value
    self.totalTokenQty = token_quantity
    self.invariant = msg.value * token_quantity
    assert self.invariant > 0

# Sells ether to the contract in exchange for tokens (minus a fee)
@public
@payable
def ethToTokens():
    fee: wei_value = msg.value / 500
    eth_in_purchase: wei_value = msg.value - fee
    new_total_eth: wei_value = self.totalEthQty + eth_in_purchase
    new_total_tokens: uint256(currency_value) = self.invariant / new_total_eth
    self.token_address.transfer(msg.sender, as_unitless_number(self.totalTokenQty - new_total_tokens))
    self.totalEthQty = new_total_eth
    self.totalTokenQty = new_total_tokens

# Sells tokens to the contract in exchange for ether
@public
def tokensToEth(sell_quantity: uint256(currency_value)):
    self.token_address.transferFrom(msg.sender, self, as_unitless_number(sell_quantity))
    new_total_tokens: uint256(currency_value) = self.totalTokenQty + sell_quantity
    new_total_eth: wei_value = self.invariant / new_total_tokens
    eth_to_send: wei_value = self.totalEthQty - new_total_eth
    send(msg.sender, eth_to_send)
    self.totalEthQty = new_total_eth
    self.totalTokenQty = new_total_tokens

# Owner can withdraw their funds and destroy the market maker
@public
def ownerWithdraw():
    assert self.owner == msg.sender
    self.token_address.transfer(self.owner, as_unitless_number(self.totalTokenQty))
    selfdestruct(self.owner)

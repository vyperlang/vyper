total_eth_qty: public(wei_value)
total_token_qty: public(currency_value)
# Constant set in `initiate` that's used to calculate
# the amount of ether/tokens that are exchanged
invariant: public(num(wei * currency))
token_address: address(ERC20)
owner: public(address)

# Sets the on chain market maker with its owner, intial token quantity,
# and initial ether quantity
@public
@payable
def initiate(token_addr: address, token_quantity: currency_value):
    assert self.invariant == 0
    self.token_address = token_addr
    self.token_address.transferFrom(msg.sender, self, as_num256(token_quantity))
    self.owner = msg.sender
    self.total_eth_qty = msg.value
    self.total_token_qty = token_quantity
    self.invariant = msg.value * token_quantity
    assert self.invariant > 0

# Sells ether to the contract in exchange for tokens (minus a fee)
@public
@payable
def eth_to_tokens():
    fee: wei_value = msg.value / 500
    eth_in_purchase: wei_value = msg.value - fee
    new_total_eth: wei_value = self.total_eth_qty + eth_in_purchase
    new_total_tokens: currency_value = self.invariant / new_total_eth
    self.token_address.transfer(msg.sender,
                                as_num256(self.total_token_qty - new_total_tokens))
    self.total_eth_qty = new_total_eth
    self.total_token_qty = new_total_tokens

# Sells tokens to the contract in exchange for ether
@public
def tokens_to_eth(sell_quantity: currency_value):
    self.token_address.transferFrom(msg.sender, self, as_num256(sell_quantity))
    new_total_tokens: currency_value = self.total_token_qty + sell_quantity
    new_total_eth: wei_value = self.invariant / new_total_tokens
    eth_to_send: wei_value = self.total_eth_qty - new_total_eth
    send(msg.sender, eth_to_send)
    self.total_eth_qty = new_total_eth
    self.total_token_qty = new_total_tokens

# Owner can withdraw their funds and destroy the market maker
@public
def owner_withdraw():
    assert self.owner == msg.sender
    self.token_address.transfer(self.owner, as_num256(self.total_token_qty))
    selfdestruct(self.owner)

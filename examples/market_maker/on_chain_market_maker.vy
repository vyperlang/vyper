from vyper.interfaces import ERC20


total_eth_qty: public(uint256)
total_token_qty: public(uint256)
# Constant set in `initiate` that's used to calculate
# the amount of ether/tokens that are exchanged
invariant: public(uint256)
token_address: ERC20
owner: public(address)

# Sets the on chain market maker with its owner, intial token quantity,
# and initial ether quantity
@external
@payable
def initiate(token_addr: address, token_quantity: uint256):
    assert self.invariant == 0
    self.token_address = ERC20(token_addr)
    self.token_address.transferFrom(msg.sender, self, token_quantity)
    self.owner = msg.sender
    self.total_eth_qty = msg.value
    self.total_token_qty = token_quantity
    self.invariant = msg.value * token_quantity
    assert self.invariant > 0

# Sells ether to the contract in exchange for tokens (minus a fee)
@external
@payable
def eth_to_tokens():
    fee: uint256 = msg.value / 500
    eth_in_purchase: uint256 = msg.value - fee
    new_total_eth: uint256 = self.total_eth_qty + eth_in_purchase
    new_total_tokens: uint256 = self.invariant / new_total_eth
    self.token_address.transfer(msg.sender, self.total_token_qty - new_total_tokens)
    self.total_eth_qty = new_total_eth
    self.total_token_qty = new_total_tokens

# Sells tokens to the contract in exchange for ether
@external
def tokens_to_eth(sell_quantity: uint256):
    self.token_address.transferFrom(msg.sender, self, sell_quantity)
    new_total_tokens: uint256 = self.total_token_qty + sell_quantity
    new_total_eth: uint256 = self.invariant / new_total_tokens
    eth_to_send: uint256 = self.total_eth_qty - new_total_eth
    send(msg.sender, eth_to_send)
    self.total_eth_qty = new_total_eth
    self.total_token_qty = new_total_tokens

# Owner can withdraw their funds and destroy the market maker
@external
def owner_withdraw():
    assert self.owner == msg.sender
    self.token_address.transfer(self.owner, self.total_token_qty)
    selfdestruct(self.owner)

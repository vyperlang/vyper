total_eth_qty: public(wei_value)
total_token_qty: public(num)
invariant: public(wei_value)
token_address: address(ERC20)
owner: public(address)

@public
@payable
def initiate(token_addr: address, token_quantity: num):
    assert self.invariant == 0
    self.token_address = token_addr
    self.token_address.transferFrom(msg.sender, self, as_num256(token_quantity))
    self.owner = msg.sender
    self.total_eth_qty = msg.value
    self.total_token_qty = token_quantity
    self.invariant = msg.value
    assert self.invariant > 0

@public
@payable
def eth_to_tokens():
    fee = msg.value / 500
    eth_in_purchase = msg.value - fee
    new_total_eth = self.total_eth_qty + eth_in_purchase
    new_total_tokens = self.invariant / new_total_eth
    self.token_address.transfer(msg.sender,
                                as_num256(self.total_token_qty - new_total_tokens))
    self.total_token_qty = new_total_tokens

@public
def tokens_to_eth(sell_quantity: num):
    # self.token_address.transferFrom(msg.sender, self, as_num256(sell_quantity))
    new_total_tokens = self.total_token_qty + sell_quantity
    new_total_eth = self.invariant / new_total_tokens
    eth_to_send = self.total_eth_qty - new_total_eth
    send(msg.sender, eth_to_send)
    self.total_eth_qty = new_total_eth

@public
def owner_withdraw():
    assert self.owner == msg.sender
    self.token_address.transfer(self.owner, as_num256(self.total_token_qty))
    selfdestruct(self.owner)

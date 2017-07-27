# Own shares of a company!
company: address
avail_shares: num
total_shares: num
price: wei_value

stockholders: {account: address, stock: num}[num]
stockholder_lookup: num[address]
num_stockholders: num
not_found: num = -1

@internal
def lookup(_account: address) -> num:
    return self.stockholder_lookup[_account]

@internal
def append(_account: address, _stock: num):
    assert self.lookup(_account) == self.not_found
    
    self.stockholders[self.num_stockholders] = {account: _account, stock: _stock}
    self.stockholder_lookup[_account] = self.num_stockholders
    self.num_stockholders += 1

# Setup company
def __init__(_company: address, _total_shares: num, initial_price: wei_value):
    assert _total_shares > 0
    assert initial_price > 0
    
    self.company = _company
    self.avail_shares = _total_shares
    self.total_shares = _total_shares
    self.num_stockholders = 0
    
    self.price = initial_price

@payable
def buy_stock():
    buy_order = msg.value / self.price # round_down to nearest whole num
    # There are enough shares to buy
    assert self.avail_shares >= buy_order
    # Full amount is given to company
    send(self.company, msg.value)
    # Find (or create) shareholder account
    # Take the shares off the market and give to that account
    self.avail_shares -= buy_order
    idx = self.lookup(msg.sender)
    if idx > self.not_found:
        # Account exists, so add to that account
        self.stockholders[idx].stock += buy_order
        return
    # Not in stockholders list, so add account
    self.append(msg.sender, buy_order)

@payable
def sell_stock():
    sell_order = msg.value / self.price # round_down
    
    idx = self.lookup(msg.sender)
    assert idx > self.not_found
    # Can only sell as much stock as you own
    if self.stockholders[idx].stock > sell_order:
        sell_order = self.stockholders[idx].stock
    # Sell the stock, send the proceeds to the user
    self.stockholders[idx].stock -= sell_order
    send(msg.sender, sell_order * self.price)
    # Put the stock back on the market
    self.avail_shares += sell_order

@constant
def valuation() -> wei_value:
    # Valuation is shares off the market times asking price
    return (self.total_shares - self.avail_shares) * self.price

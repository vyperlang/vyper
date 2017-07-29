# Own shares of a company!
company: address
avail_shares: num
total_shares: num
price: wei_value

holdings: num[address]

# Setup company
def __init__(_company: address, _total_shares: num, initial_price: wei_value):
    assert _total_shares > 0
    assert initial_price > 0
    
    self.company = _company
    self.avail_shares = _total_shares
    self.total_shares = _total_shares
    
    self.price = initial_price

# Give value to company and get stock in return
@payable
def buy_stock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    buy_order = msg.value / self.price # rounds down

    # There are enough shares to buy
    assert self.avail_shares >= buy_order
    
    # Take the shares off the market and give to stockholder
    self.avail_shares -= buy_order
    if self.holdings[msg.sender]:
        # Account exists, so add to that account
        self.holdings[msg.sender] += buy_order
    else:
        # Not currently a stockholder, so add them
        self.holdings[msg.sender] = buy_order

# Give stock back to company and get my money back!
def sell_stock(sell_order: num):
    # Can only sell as much stock as you own
    assert self.holdings[msg.sender] >= sell_order

    # Sell the stock, send the proceeds to the user
    self.holdings[msg.sender] -= sell_order
    send(msg.sender, sell_order * self.price)

    # Put the stock back on the market
    self.avail_shares += sell_order

@constant
def valuation() -> wei_value:
    return (self.total_shares - self.avail_shares) * self.price

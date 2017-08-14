# Own shares of a company!
company: address
total_shares: currency_value
price: num (wei / currency)

holdings: currency_value[address]

# Setup company
def __init__(_company: address, _total_shares: currency_value, 
        initial_price: num(wei / currency) ):
    assert _total_shares > 0
    assert initial_price > 0
    
    self.company = _company
    self.total_shares = _total_shares
    
    self.price = initial_price
    
    # Company holds all the shares at first, but can sell them all
    self.holdings[self.company] = _total_shares

# Give value to company and get stock in return
@payable
def buy_stock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    buy_order = msg.value / self.price # rounds down

    # There are enough shares to buy
    assert self.holdings[self.company] >= buy_order
    
    # Take the shares off the market and give to stockholder
    self.holdings[self.company] -= buy_order
    self.holdings[msg.sender] += buy_order

# Give stock back to company and get my money back!
def sell_stock(sell_order: currency_value):
    # Can only sell as much stock as you own
    assert self.holdings[msg.sender] >= sell_order

    # Sell the stock, send the proceeds to the user
    # and put the stock back on the market
    self.holdings[msg.sender] -= sell_order
    self.holdings[self.company] += sell_order
    send(msg.sender, sell_order * self.price)

@constant
def valuation() -> wei_value:
    return (self.total_shares - self.holdings[self.company]) * self.price

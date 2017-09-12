# Own shares of a company!
company: public(address)
total_shares: public(currency_value)
price: public(num (wei / currency))

# Store ledger of stockholder holdings
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

@constant
def stock_available() -> currency_value:
    return self.holdings[self.company]

# Give value to company and get stock in return
@payable
def buy_stock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    buy_order = msg.value / self.price # rounds down

    # There are enough shares to buy
    assert self.stock_available() >= buy_order
    
    # Take the shares off the market and give to stockholder
    self.holdings[self.company] -= buy_order
    self.holdings[msg.sender] += buy_order

# So someone can find out how much they have
@constant
def get_holding(_stockholder: address) -> currency_value:
    return self.holdings[_stockholder]

# The amount the company has on hand in cash
@constant
def cash() -> wei_value:
    return self.balance

# Give stock back to company and get my money back!
def sell_stock(sell_order: currency_value):
    # Can only sell as much stock as you own
    assert self.get_holding(msg.sender) >= sell_order
    # Company can pay you
    assert self.cash() >= (sell_order * self.price)

    # Sell the stock, send the proceeds to the user
    # and put the stock back on the market
    self.holdings[msg.sender] -= sell_order
    self.holdings[self.company] += sell_order
    send(msg.sender, sell_order * self.price)

# Transfer stock from one stockholder to another
# (Assumes the receiver is given some compensation, but not enforced)
def transfer_stock(receiver: address, transfer_order: currency_value):
    # Can only trade as much stock as you own
    assert self.get_holding(msg.sender) >= transfer_order
    
    # Debit sender's stock and add to receiver's address
    self.holdings[msg.sender] -= transfer_order
    self.holdings[receiver] += transfer_order

# Allows the company to pay someone for services rendered
def pay_bill(vendor: address, amount: wei_value):
    # Only the company can pay people
    assert msg.sender == self.company
    # And only if there's enough to pay them with
    assert self.cash() >= amount

    # Pay the bill!
    send(vendor, amount)

# The amount a company has raised in the stock offering
@constant
def worth() -> wei_value:
    return (self.total_shares - self.holdings[self.company]) * self.price

# The balance sheet of the company
@constant
def debt() -> wei_value:
    return self.cash() - self.worth()

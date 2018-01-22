# Financial events the contract logs
Transfer: __log__({_from: indexed(address), _to: indexed(address), _value: currency_value})
Buy: __log__({_buyer: indexed(address), _buy_order: currency_value})
Sell: __log__({_seller: indexed(address), _sell_order: currency_value})
Pay: __log__({_vendor: indexed(address), _amount: wei_value})

# Own shares of a company!
company: public(address)
total_shares: public(currency_value)
price: public(num (wei / currency))

# Store ledger of stockholder holdings
holdings: currency_value[address]

# Setup company
@public
def __init__(_company: address, _total_shares: currency_value,
        initial_price: num(wei / currency) ):
    assert _total_shares > 0
    assert initial_price > 0

    self.company = _company
    self.total_shares = _total_shares

    self.price = initial_price

    # Company holds all the shares at first, but can sell them all
    self.holdings[self.company] = _total_shares

@public
@constant
def stock_available() -> currency_value:
    return self.holdings[self.company]

# Give value to company and get stock in return
@public
@payable
def buy_stock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    buy_order: currency_value = msg.value / self.price # rounds down

    # There are enough shares to buy
    assert self.stock_available() >= buy_order

    # Take the shares off the market and give to stockholder
    self.holdings[self.company] -= buy_order
    self.holdings[msg.sender] += buy_order

    # Log the buy event
    log.Buy(msg.sender, buy_order)

# So someone can find out how much they have
@public
@constant
def get_holding(_stockholder: address) -> currency_value:
    return self.holdings[_stockholder]

# The amount the company has on hand in cash
@public
@constant
def cash() -> wei_value:
    return self.balance

# Give stock back to company and get my money back!
@public
def sell_stock(sell_order: currency_value):
    assert sell_order > 0 # Otherwise, will fail at send() below
    # Can only sell as much stock as you own
    assert self.get_holding(msg.sender) >= sell_order
    # Company can pay you
    assert self.cash() >= (sell_order * self.price)

    # Sell the stock, send the proceeds to the user
    # and put the stock back on the market
    self.holdings[msg.sender] -= sell_order
    self.holdings[self.company] += sell_order
    send(msg.sender, sell_order * self.price)

    # Log sell event
    log.Sell(msg.sender, sell_order)

# Transfer stock from one stockholder to another
# (Assumes the receiver is given some compensation, but not enforced)
@public
def transfer_stock(receiver: address, transfer_order: currency_value):
    assert transfer_order > 0 # AUDIT revealed this!
    # Can only trade as much stock as you own
    assert self.get_holding(msg.sender) >= transfer_order

    # Debit sender's stock and add to receiver's address
    self.holdings[msg.sender] -= transfer_order
    self.holdings[receiver] += transfer_order

    # Log the transfer event
    log.Transfer(msg.sender, receiver, transfer_order)

# Allows the company to pay someone for services rendered
@public
def pay_bill(vendor: address, amount: wei_value):
    # Only the company can pay people
    assert msg.sender == self.company
    # And only if there's enough to pay them with
    assert self.cash() >= amount

    # Pay the bill!
    send(vendor, amount)

    # Log payment event
    log.Pay(vendor, amount)

# The amount a company has raised in the stock offering
@public
@constant
def debt() -> wei_value:
    return (self.total_shares - self.holdings[self.company]) * self.price

# The balance sheet of the company
@public
@constant
def worth() -> wei_value:
    return self.cash() - self.debt()

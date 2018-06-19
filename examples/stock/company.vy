units: {
    currency_value: "Currency Value"
}

# Financial events the contract logs
Transfer: event({_from: indexed(address), _to: indexed(address), _value: uint256(currency_value)})
Buy: event({_buyer: indexed(address), _buy_order: uint256(currency_value)})
Sell: event({_seller: indexed(address), _sell_order: uint256(currency_value)})
Pay: event({_vendor: indexed(address), _amount: wei_value})

# Initiate the variables for the company and it's own shares.
company: public(address)
total_shares: public(uint256(currency_value))
price: public(uint256 (wei / currency_value))

# Store a ledger of stockholder holdings.
holdings: uint256(currency_value)[address]

# Set up the company.
@public
def __init__(_company: address, _total_shares: uint256(currency_value),
        initial_price: uint256(wei / currency_value) ):
    assert _total_shares > 0
    assert initial_price > 0

    self.company = _company
    self.total_shares = _total_shares
    self.price = initial_price

    # The company holds all the shares at first, but can sell them all.
    self.holdings[self.company] = _total_shares

@public
@constant
def stock_available() -> uint256(currency_value):
    return self.holdings[self.company]

# Give some value to the company and get stock in return.
@public
@payable
def buy_stock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    buy_order: uint256(currency_value) = msg.value / self.price # rounds down

    # Check that there are enough shares to buy.
    assert self.stock_available() >= buy_order

    # Take the shares off the market and give them to the stockholder.
    self.holdings[self.company] -= buy_order
    self.holdings[msg.sender] += buy_order

    # Log the buy event.
    log.Buy(msg.sender, buy_order)

# Find out how much stock any address (that's owned by someone) has.
@public
@constant
def get_holding(_stockholder: address) -> uint256(currency_value):
    return self.holdings[_stockholder]

# Return the amount the company has on hand in cash.
@public
@constant
def cash() -> wei_value:
    return self.balance

# Give stock back to the company and get money back as ETH.
@public
def sell_stock(sell_order: uint256(currency_value)):
    assert sell_order > 0 # Otherwise, this would fail at send() below,
        # due to an OOG error (there would be zero value available for gas).
    # You can only sell as much stock as you own.
    assert self.get_holding(msg.sender) >= sell_order
    # Check that the company can pay you.
    assert self.cash() >= (sell_order * self.price)

    # Sell the stock, send the proceeds to the user
    # and put the stock back on the market.
    self.holdings[msg.sender] -= sell_order
    self.holdings[self.company] += sell_order
    send(msg.sender, sell_order * self.price)

    # Log the sell event.
    log.Sell(msg.sender, sell_order)

# Transfer stock from one stockholder to another. (Assume that the
# receiver is given some compensation, but this is not enforced.)
@public
def transfer_stock(receiver: address, transfer_order: uint256(currency_value)):
    assert transfer_order > 0 # This is similar to sell_stock above.
    # Similarly, you can only trade as much stock as you own.
    assert self.get_holding(msg.sender) >= transfer_order

    # Debit the sender's stock and add to the receiver's address.
    self.holdings[msg.sender] -= transfer_order
    self.holdings[receiver] += transfer_order

    # Log the transfer event.
    log.Transfer(msg.sender, receiver, transfer_order)

# Allow the company to pay someone for services rendered.
@public
def pay_bill(vendor: address, amount: wei_value):
    # Only the company can pay people.
    assert msg.sender == self.company
    # Also, it can pay only if there's enough to pay them with.
    assert self.cash() >= amount

    # Pay the bill!
    send(vendor, amount)

    # Log the payment event.
    log.Pay(vendor, amount)

# Return the amount in wei that a company has raised in stock offerings.
@public
@constant
def debt() -> wei_value:
    return (self.total_shares - self.holdings[self.company]) * self.price

# Return the cash holdings minus the debt of the company.
# The share debt or liability only is included here,
# but of course all other liabilities can be included.
@public
@constant
def worth() -> wei_value:
    return self.cash() - self.debt()

#pragma version >0.3.10

# Financial events the contract logs

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

event Buy:
    buyer: indexed(address)
    buy_order: uint256

event Sell:
    seller: indexed(address)
    sell_order: uint256

event Pay:
    vendor: indexed(address)
    amount: uint256


# Initiate the variables for the company and it's own shares.
company: public(address)
totalShares: public(uint256)
price: public(uint256)

# Store a ledger of stockholder holdings.
holdings: HashMap[address, uint256]

# Set up the company.
@deploy
def __init__(_company: address, _total_shares: uint256, initial_price: uint256):
    assert _total_shares > 0
    assert initial_price > 0

    self.company = _company
    self.totalShares = _total_shares
    self.price = initial_price

    # The company holds all the shares at first, but can sell them all.
    self.holdings[self.company] = _total_shares

# Public function to allow external access to _stockAvailable
@view
@external
def stockAvailable() -> uint256:
    return self._stockAvailable()

# Give some value to the company and get stock in return.
@external
@payable
def buyStock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    buy_order: uint256 = msg.value // self.price # rounds down

    # Check that there are enough shares to buy.
    assert self._stockAvailable() >= buy_order

    # Take the shares off the market and give them to the stockholder.
    self.holdings[self.company] -= buy_order
    self.holdings[msg.sender] += buy_order

    # Log the buy event.
    log Buy(msg.sender, buy_order)

# Public function to allow external access to _getHolding
@view
@external
def getHolding(_stockholder: address) -> uint256:
    return self._getHolding(_stockholder)

# Return the amount the company has on hand in cash.
@view
@external
def cash() -> uint256:
    return self.balance

# Give stock back to the company and get money back as ETH.
@external
def sellStock(sell_order: uint256):
    assert sell_order > 0 # Otherwise, this would fail at send() below,
        # due to an OOG error (there would be zero value available for gas).
    # You can only sell as much stock as you own.
    assert self._getHolding(msg.sender) >= sell_order
    # Check that the company can pay you.
    assert self.balance >= (sell_order * self.price)

    # Sell the stock, send the proceeds to the user
    # and put the stock back on the market.
    self.holdings[msg.sender] -= sell_order
    self.holdings[self.company] += sell_order
    send(msg.sender, sell_order * self.price)

    # Log the sell event.
    log Sell(msg.sender, sell_order)

# Transfer stock from one stockholder to another. (Assume that the
# receiver is given some compensation, but this is not enforced.)
@external
def transferStock(receiver: address, transfer_order: uint256):
    assert transfer_order > 0 # This is similar to sellStock above.
    # Similarly, you can only trade as much stock as you own.
    assert self._getHolding(msg.sender) >= transfer_order

    # Debit the sender's stock and add to the receiver's address.
    self.holdings[msg.sender] -= transfer_order
    self.holdings[receiver] += transfer_order

    # Log the transfer event.
    log Transfer(msg.sender, receiver, transfer_order)

# Allow the company to pay someone for services rendered.
@external
def payBill(vendor: address, amount: uint256):
    # Only the company can pay people.
    assert msg.sender == self.company
    # Also, it can pay only if there's enough to pay them with.
    assert self.balance >= amount

    # Pay the bill!
    send(vendor, amount)

    # Log the payment event.
    log Pay(vendor, amount)

# Public function to allow external access to _debt
@view
@external
def debt() -> uint256:
    return self._debt()

# Return the cash holdings minus the debt of the company.
# The share debt or liability only is included here,
# but of course all other liabilities can be included.
@view
@external
def worth() -> uint256:
    return self.balance - self._debt()

# Return the amount in wei that a company has raised in stock offerings.
@view
@internal
def _debt() -> uint256:
    return (self.totalShares - self._stockAvailable()) * self.price

# Find out how much stock the company holds
@view
@internal
def _stockAvailable() -> uint256:
    return self.holdings[self.company]

# Find out how much stock any address (that's owned by someone) has.
@view
@internal
def _getHolding(_stockholder: address) -> uint256:
    return self.holdings[_stockholder]

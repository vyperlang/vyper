from vyper.interfaces import ERC201

implements: ERC201

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


name: public(String[64])
symbol: public(String[32])
decimals: public(uint256)


# Initiate the variables for the company and it's own shares.
company: public(address)
total_supply: public(uint256)
# price: public(uint256)

# Store a ledger of stockholder balanceOf.
balanceOf: public(HashMap[address, uint256])

# Set up the company.
@external
def __init__(_name: String[64], _symbol: String[32], _decimals: uint256):

    # assert _total_shares > 0
    # assert initial_price > 0

    # init_supply: uint256 = _total_shares * 10 ** _decimals
    self.name = _name
    self.symbol = _symbol
    self.decimals = _decimals
    # self.balanceOf[msg.sender] = 0
    # total_supply should equal 0 but leave for now
    self.total_supply = 0

    # self.minter = msg.sender
    self.company = msg.sender

    # self.price = 1000000000000000000

    # The company holds all the shares at first, but can sell them all.
    # log Transfer(ZERO_ADDRESS, msg.sender, init_supply)


# Find out how much stock the company holds
@view
@external
def stockAvailable() -> uint256:
    return self.balanceOf[self.company]

# Public function to allow external access to _stockAvailable
# @view
# @external
# def stockAvailable() -> uint256:
#     return self._stockAvailable()



@internal
def _mint(_to: address, _value: uint256):
    """
    @dev Mint an amount of the token and assigns it to an account.
         This encapsulates the modification of balances such that the
         proper events are emitted.
    @param _to The account that will receive the created tokens.
    @param _value The amount that will be created.
    """
    assert _to != ZERO_ADDRESS    
    self.total_supply += _value
    self.balanceOf[_to] += _value
    log Transfer(ZERO_ADDRESS, _to, _value)


# Give some value to the company and get stock in return.
@external
@payable
def buyStock():
    # Note: full amount is given to company (no fractional shares),
    #       so be sure to send exact amount to buy shares
    # buy_order: uint256 = msg.value / self.price # rounds down

    # Check that there are enough shares to buy.
    # assert self._stockAvailable() >= buy_order

    # Take the shares off the market and give them to the stockholder.
    # self.balanceOf[self.company] -= buy_order
    # self.balanceOf[msg.sender] += buy_order

    self._mint(msg.sender, msg.value)

    # Log the buy event.
    log Buy(msg.sender, msg.value)

# Find out how much stock any address (that's owned by someone) has.
@view
@internal
def _getHolding(_stockholder: address) -> uint256:
    return self.balanceOf[_stockholder]

# Public function to allow external access to _getHolding
@view
@external
def getHolding(_stockholder: address) -> uint256:
    return self._getHolding(_stockholder)


# # Return the amount the company has on hand in cash.
# @view
# @external
# def cash() -> uint256:
#     return self.balance


@internal
def _burn(_to: address, _value: uint256):
    """
    @dev Internal function that burns an amount of the token of a given
         account.
    @param _to The account whose tokens will be burned.
    @param _value The amount that will be burned.
    """
    assert _to != ZERO_ADDRESS
    self.total_supply -= _value
    self.balanceOf[_to] -= _value
    log Transfer(_to, ZERO_ADDRESS, _value)


# Give stock back to the company and get money back as ETH.
@external
def sellStock(sell_order: uint256):
    assert sell_order > 0 # Otherwise, this would fail at send() below,
        # due to an OOG error (there would be zero value available for gas).
    # You can only sell as much stock as you own.

    assert self._getHolding(msg.sender) >= sell_order
    # Check that the company can pay you.
    assert self.balance >= sell_order

    # Sell the stock, send the proceeds to the user
    # and put the stock back on the market.
    
    self._burn(msg.sender, sell_order)

    send(msg.sender, sell_order)

    # Log the sell event.
    log Sell(msg.sender, sell_order)


# @view
# @external
# def totalSupply() -> uint256:
#     """
#     @dev Total number of tokens in existence.
#     """
#     return self.total_supply


# Transfer stock from one stockholder to another. (Assume that the
# receiver is given some compensation, but this is not enforced.)
@external
def transfer(receiver: address, transfer_order: uint256) -> bool:
    assert transfer_order > 0 # This is similar to sellStock above.
    # Similarly, you can only trade as much stock as you own.
    assert self._getHolding(msg.sender) >= transfer_order

    # Debit the sender's stock and add to the receiver's address.
    self.balanceOf[msg.sender] -= transfer_order
    self.balanceOf[receiver] += transfer_order

    # Log the transfer event.
    log Transfer(msg.sender, receiver, transfer_order)
    return True








# @external
# def mint(_value: uint256):
#     """
#     @dev Mint an amount of the token of msg.sender.
#     @param _value The amount that will be minted.
#     """
#     assert msg.sender == self.company
#     self._mint(msg.sender, _value)


# @external
# def mintTo(_to: address, _value: uint256):
#     """
#     @dev Mint an amount of the token from a given account.
#     @param _to The account whose tokens will be minted.
#     @param _value The amount that will be minted.
#     """
#     assert msg.sender == self.company
#     self._mint(_to, _value)



# @external
# def burn(_value: uint256):
#     """
#     @dev Burn an amount of the token of msg.sender.
#     @param _value The amount that will be burned.
#     """
#     self._burn(msg.sender, _value)


# @external
# def burnFrom(_to: address, _value: uint256):
#     """
#     @dev Burn an amount of the token from a given account.
#     @param _to The account whose tokens will be burned.
#     @param _value The amount that will be burned.
#     """
#     assert msg.sender == self.company
#     self._burn(_to, _value)

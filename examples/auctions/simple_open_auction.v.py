# Open Auction

# Auction params
# Beneficiary receives money from the highest bidder
beneficiary: public(address)
auction_start: public(timestamp)
auction_end: public(timestamp)

# Current state of auction
highest_bidder: public(address)
highest_bid: public(wei_value)

# Set to true at the end, disallows any change
ended: public(bool)

# Create a simple auction with `_bidding_time`
# seconds bidding time on behalf of the
# beneficiary address `_beneficiary`.
@public
def __init__(_beneficiary: address, _bidding_time: timedelta):
    self.beneficiary = _beneficiary
    self.auction_start = block.timestamp
    self.auction_end = self.auction_start + _bidding_time

# Bid on the auction with the value sent
# together with this transaction.
# The value will only be refunded if the
# auction is not won.
@public
@payable
def bid():
    # Check if bidding period is over.
    assert block.timestamp < self.auction_end
    # Check if bid is high enough
    assert msg.value > self.highest_bid
    if not self.highest_bid == 0:
        # Sends money back to the previous highest bidder
        send(self.highest_bidder,self.highest_bid)
    self.highest_bidder = msg.sender
    self.highest_bid = msg.value


# End the auction and send the highest bid
# to the beneficiary.
@public
def auction_end():
    # It is a good guideline to structure functions that interact
    # with other contracts (i.e. they call functions or send Ether)
    # into three phases:
    # 1. checking conditions
    # 2. performing actions (potentially changing conditions)
    # 3. interacting with other contracts
    # If these phases are mixed up, the other contract could call
    # back into the current contract and modify the state or cause
    # effects (Ether payout) to be performed multiple times.
    # If functions called internally include interaction with external
    # contracts, they also have to be considered interaction with
    # external contracts.

    # 1. Conditions
    # Check if auction endtime has been reached
    assert block.timestamp >= self.auction_end
    # Check if this function has already been called
    assert not self.ended

    # 2. Effects
    self.ended = True

    # 3. Interaction
    send(self.beneficiary, self.highest_bid)

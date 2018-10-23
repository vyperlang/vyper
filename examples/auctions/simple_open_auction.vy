# Open Auction

# Auction params
# Beneficiary receives money from the highest bidder
beneficiary: public(address)
auctionStart: public(timestamp)
auctionEnd: public(timestamp)

# Current state of auction
highestBidder: public(address)
highestBid: public(wei_value)

# Set to true at the end, disallows any change
ended: public(bool)

# Create a simple auction with `_biddingTime`
# seconds bidding time on behalf of the
# beneficiary address `_beneficiary`.
@public
def __init__(_beneficiary: address, _biddingTime: timedelta):
    self.beneficiary = _beneficiary
    self.auctionStart = block.timestamp
    self.auctionEnd = self.auctionStart + _biddingTime

# Bid on the auction with the value sent
# together with this transaction.
# The value will only be refunded if the
# auction is not won.
@public
@payable
def bid():
    # Check if bidding period is over.
    assert block.timestamp < self.auctionEnd
    # Check if bid is high enough
    assert msg.value > self.highestBid
    if not self.highestBid == 0:
        # Sends money back to the previous highest bidder
        send(self.highestBidder, self.highestBid)
    self.highestBidder = msg.sender
    self.highestBid = msg.value


# End the auction and send the highest bid
# to the beneficiary.
@public
def endAuction():
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
    assert block.timestamp >= self.auctionEnd
    # Check if this function has already been called
    assert not self.ended

    # 2. Effects
    self.ended = True

    # 3. Interaction
    send(self.beneficiary, self.highestBid)

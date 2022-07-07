# @version 0.3.4
# Open Auction

# Auction params
# Beneficiary receives money from the highest bidder
beneficiary: public(address)
auction_start: public(uint256)
auction_end: public(uint256)

# Current state of auction
highest_bidder: public(address)
highest_bid: public(uint256)

# Set to true at the end, disallows any change
ended: public(bool)

# Keep track of refunded bids so we can follow the withdraw pattern
pending_returns: public(HashMap[address, uint256])

# Create a simple auction with `auction_start` and
# `bidding_time` seconds bidding time on behalf of the
# beneficiary address `beneficiary`.
@external
def __init__(beneficiary: address, auction_start: uint256, bidding_time: uint256):
    self.beneficiary = beneficiary
    self.auction_start = auction_start  # auction start time can be in the past, present or future
    self.auction_end = self.auction_start + bidding_time
    assert block.timestamp < self.auction_end # auction end time should be in the future

# Bid on the auction with the value sent
# together with this transaction.
# The value will only be refunded if the
# auction is not won.
@external
@payable
def bid():
    # Check if bidding period has started.
    assert block.timestamp >= self.auction_start
    # Check if bidding period is over.
    assert block.timestamp < self.auction_end
    # Check if bid is high enough
    assert msg.value > self.highest_bid
    # Track the refund for the previous high bidder
    self.pending_returns[self.highest_bidder] += self.highest_bid
    # Track new high bid
    self.highest_bidder = msg.sender
    self.highest_bid = msg.value

# Withdraw a previously refunded bid. The withdraw pattern is
# used here to avoid a security issue. If refunds were directly
# sent as part of bid(), a malicious bidding contract could block
# those refunds and thus block new higher bids from coming in.
@external
def withdraw():
    pending_amount: uint256 = self.pending_returns[msg.sender]
    self.pending_returns[msg.sender] = 0
    send(msg.sender, pending_amount)

# End the auction and send the highest bid
# to the beneficiary.
@external
def end_auction():
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

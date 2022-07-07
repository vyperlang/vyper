# Blind Auction # Adapted to Vyper from [Solidity by Example](https://github.com/ethereum/solidity/blob/develop/docs/solidity-by-example.rst#blind-auction-1)

struct Bid:
  blinded_bid: bytes32
  deposit: uint256

# Note: because Vyper does not allow for dynamic arrays, we have limited the
# number of bids that can be placed by one address to 128 in this example
MAX_BIDS: constant(int128) = 128

# Event for logging that auction has ended
event AuctionEnded:
    highest_bidder: address
    highest_bid: uint256

# Auction parameters
beneficiary: public(address)
bidding_end: public(uint256)
reveal_end: public(uint256)

# Set to true at the end of auction, disallowing any new bids
ended: public(bool)

# Final auction state
highest_bid: public(uint256)
highest_bidder: public(address)

# State of the bids
bids: HashMap[address, Bid[128]]
bid_counts: HashMap[address, int128]

# Allowed withdrawals of previous bids
pending_returns: HashMap[address, uint256]


# Create a blinded auction with `bidding_time` seconds bidding time and
# `reveal_time` seconds reveal time on behalf of the beneficiary address
# `beneficiary`.
@external
def __init__(beneficiary: address, bidding_time: uint256, reveal_time: uint256):
    self.beneficiary = beneficiary
    self.bidding_end = block.timestamp + bidding_time
    self.reveal_end = self.bidding_end + reveal_time


# Place a blinded bid with:
#
# blinded_bid = keccak256(concat(
#       convert(value, bytes32),
#       convert(fake, bytes32),
#       secret)
# )
#
# The sent ether is only refunded if the bid is correctly revealed in the
# revealing phase. The bid is valid if the ether sent together with the bid is
# at least "value" and "fake" is not true. Setting "fake" to true and sending
# not the exact amount are ways to hide the real bid but still make the
# required deposit. The same address can place multiple bids.
@external
@payable
def bid(blinded_bid: bytes32):
    # Check if bidding period is still open
    assert block.timestamp < self.bidding_end

    # Check that payer hasn't already placed maximum number of bids
    num_bids: int128 = self.bid_counts[msg.sender]
    assert num_bids < MAX_BIDS

    # Add bid to mapping of all bids
    self.bids[msg.sender][num_bids] = Bid({
        blinded_bid: blinded_bid,
        deposit: msg.value
        })
    self.bid_counts[msg.sender] += 1


# Returns a boolean value, `True` if bid placed successfully, `False` otherwise.
@internal
def place_bid(bidder: address, amount: uint256) -> bool:
    # If bid is less than highest bid, bid fails
    if amount <= self.highest_bid:
        return False

    # Refund the previously highest bidder
    if self.highest_bidder != ZERO_ADDRESS:
        self.pending_returns[self.highest_bidder] += self.highest_bid

    # Place bid successfully and update auction state
    self.highest_bid = amount
    self.highest_bidder = bidder

    return True


# Reveal your blinded bids. You will get a refund for all correctly blinded
# invalid bids and for all bids except for the totally highest.
@external
def reveal(num_bids: int128, amounts: uint256[128], fakes: bool[128], secrets: bytes32[128]):
    # Check that bidding period is over
    assert block.timestamp > self.bidding_end

    # Check that reveal end has not passed
    assert block.timestamp < self.reveal_end

    # Check that number of bids being revealed matches log for sender
    assert num_bids == self.bid_counts[msg.sender]

    # Calculate refund for sender
    refund: uint256 = 0
    for i in range(MAX_BIDS):
        # Note that loop may break sooner than 128 iterations if i >= num_bids
        if i >= num_bids:
            break

        # Get bid to check
        bid_to_check: Bid = (self.bids[msg.sender])[i]

        # Check against encoded packet
        value: uint256 = amounts[i]
        fake: bool = fakes[i]
        secret: bytes32 = secrets[i]
        blinded_bid: bytes32 = keccak256(concat(
            convert(value, bytes32),
            convert(fake, bytes32),
            secret
        ))

        # Bid was not actually revealed
        # Do not refund deposit
        assert blinded_bid == bid_to_check.blinded_bid

        # Add deposit to refund if bid was indeed revealed
        refund += bid_to_check.deposit
        if not fake and bid_to_check.deposit >= value:
            if self.place_bid(msg.sender, value):
                refund -= value

        # Make it impossible for the sender to re-claim the same deposit
        zero_bytes32: bytes32 = EMPTY_BYTES32
        bid_to_check.blinded_bid = zero_bytes32

    # Send refund if non-zero
    if refund != 0:
        send(msg.sender, refund)


# Withdraw a bid that was overbid.
@external
def withdraw():
    # Check that there is an allowed pending return.
    pending_amount: uint256 = self.pending_returns[msg.sender]
    if pending_amount > 0:
        # If so, set pending returns to zero to prevent recipient from calling
        # this function again as part of the receiving call before `transfer`
        # returns (see the remark above about conditions -> effects ->
        # interaction).
        self.pending_returns[msg.sender] = 0

        # Then send return
        send(msg.sender, pending_amount)


# End the auction and send the highest bid to the beneficiary.
@external
def auction_end():
    # Check that reveal end has passed
    assert block.timestamp > self.reveal_end

    # Check that auction has not already been marked as ended
    assert not self.ended

    # Log auction ending and set flag
    log AuctionEnded(self.highest_bidder, self.highest_bid)
    self.ended = True

    # Transfer funds to beneficiary
    send(self.beneficiary, self.highest_bid)

# SimpleAuction from solidity docs.

# Parameters of the auction.
beneficiary: public(address)
auctionStart: public(timestamp)
biddingTime: public(timedelta)

# Current state of the auction.
highestBidder: public(address)
highestBid: public(wei_value)

# Allowed withdrawals of previous bids.
pendingReturns: public(wei_value[address])

# Set to true at the end, disallows any change.
ended: public(bool)

# Create a simple auction with `_biddingTime`
# seconds bidding time on behalf of the
# beneficiary address `_beneficiary`.
def __init__(_biddingTime: timedelta, _beneficiary: address):
    self.beneficiary = _beneficiary
    self.auctionStart = block.timestamp
    self.biddingTime = _biddingTime

# Bid on the auction with the value sent
# together with this transaction.
# The value will only be refunded if the
# auction is not won.
@payable
def bid():
    # No arguments are necessary, all
    # information is already part of
    # the transaction. The keyword payable
    # is required for the function to
    # be able to receive Ether.

    # Revert the call if the bidding
    # period is over.
    assert block.timestamp <= self.auctionStart + self.biddingTime

    # If the bid is not higher, send the
    # money back.
    assert msg.value > self.highestBid
    null_address: address
    if self.highestBidder != null_address:
        # Sending back the money by simply using
        # highestBidder.send(highestBid) is a security risk
        # because it could execute an untrusted contract.
        # It is always safer to let the recipients
        # withdraw their money themselves.

        self.pendingReturns[self.highestBidder] += self.highestBid;
    self.highestBidder = msg.sender
    self.highestBid    = msg.value

# Withdraw a bid that was overbid.
def withdraw() -> bool:
    amount = self.pendingReturns[msg.sender]
    if amount > 0:
        # It is important to set this to zero because the recipient
        # can call this function again as part of the receiving call
        # before `send` returns to avoid re entry attack

        self.pendingReturns[msg.sender] = 0

    send(msg.sender, amount)
    return True

# End the auction and send the highest bid
# to the beneficiary.
def auctionEnd():
    # It is a good guideline to structure functions that interact
    # with other contracts (i.e. they call functions or send Ether)
    # into three phases:
    # 1. checking conditions
    # 2. performing actions (potentially changing conditions)
    # 3. interacting with other contracts
    # If these phases are mixed up, the other contract could call
    # back into the current contract and modify the state or cause
    # effects (ether payout) to be performed multiple times.
    # If functions called internally include interaction with external
    # contracts, they also have to be considered interaction with
    # external contracts.

    # 1. Conditions
    assert block.timestamp >= (self.auctionStart + self.biddingTime)
    assert not self.ended

    # 2. Effects
    self.ended = True

    # 3. Interaction
    send(self.beneficiary, self.highestBid)

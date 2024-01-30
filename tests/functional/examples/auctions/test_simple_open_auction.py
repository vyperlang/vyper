import pytest

EXPIRY = 16


@pytest.fixture
def auction_start(w3):
    return w3.eth.get_block("latest").timestamp + 1


@pytest.fixture
def auction_contract(w3, get_contract, auction_start):
    with open("examples/auctions/simple_open_auction.vy") as f:
        contract_code = f.read()
        contract = get_contract(contract_code, *[w3.eth.accounts[0], auction_start, EXPIRY])
    return contract


def test_initial_state(w3, tester, auction_contract, auction_start):
    # Check beneficiary is correct
    assert auction_contract.beneficiary() == w3.eth.accounts[0]
    # Check start time is `auction_start`
    assert auction_contract.auctionStart() == auction_start
    # Check time difference between start time and end time is EXPIRY
    assert auction_contract.auctionEnd() == auction_contract.auctionStart() + EXPIRY
    # Check auction has not ended
    assert auction_contract.ended() is False
    # Check highest bidder is empty
    assert auction_contract.highestBidder() is None
    # Check highest bid is 0
    assert auction_contract.highestBid() == 0
    # Check end time is more than current block timestamp
    assert auction_contract.auctionEnd() >= tester.get_block_by_number("latest")["timestamp"]


def test_bid(w3, tester, auction_contract, tx_failed):
    k1, k2, k3, k4, k5 = w3.eth.accounts[:5]
    # Bidder cannot bid 0
    with tx_failed():
        auction_contract.bid(transact={"value": 0, "from": k1})
    # Bidder can bid
    auction_contract.bid(transact={"value": 1, "from": k1})
    # Check that highest bidder and highest bid have changed accordingly
    assert auction_contract.highestBidder() == k1
    assert auction_contract.highestBid() == 1
    # Bidder bid cannot equal current highest bid
    with tx_failed():
        auction_contract.bid(transact={"value": 1, "from": k1})
    # Higher bid can replace current highest bid
    auction_contract.bid(transact={"value": 2, "from": k2})
    # Check that highest bidder and highest bid have changed accordingly
    assert auction_contract.highestBidder() == k2
    assert auction_contract.highestBid() == 2
    # Multiple bidders can bid
    auction_contract.bid(transact={"value": 3, "from": k3})
    auction_contract.bid(transact={"value": 4, "from": k4})
    auction_contract.bid(transact={"value": 5, "from": k5})
    # Check that highest bidder and highest bid have changed accordingly
    assert auction_contract.highestBidder() == k5
    assert auction_contract.highestBid() == 5
    auction_contract.bid(transact={"value": 1 * 10**10, "from": k1})
    pending_return_before_outbid = auction_contract.pendingReturns(k1)
    auction_contract.bid(transact={"value": 2 * 10**10, "from": k2})
    pending_return_after_outbid = auction_contract.pendingReturns(k1)
    # Account has a greater pending return balance after being outbid
    assert pending_return_after_outbid > pending_return_before_outbid

    balance_before_withdrawal = w3.eth.get_balance(k1)
    auction_contract.withdraw(transact={"from": k1})
    balance_after_withdrawal = w3.eth.get_balance(k1)
    # Balance increases after withdrawal
    assert balance_after_withdrawal > balance_before_withdrawal
    # Pending return balance is reset to 0
    assert auction_contract.pendingReturns(k1) == 0


def test_end_auction(w3, tester, auction_contract, tx_failed):
    k1, k2, k3, k4, k5 = w3.eth.accounts[:5]
    # Fails if auction end time has not been reached
    with tx_failed():
        auction_contract.endAuction()
    auction_contract.bid(transact={"value": 1 * 10**10, "from": k2})
    # Move block timestamp forward to reach auction end time
    # tester.time_travel(tester.get_block_by_number('latest')['timestamp'] + EXPIRY)
    w3.testing.mine(EXPIRY)
    balance_before_end = w3.eth.get_balance(k1)
    auction_contract.endAuction(transact={"from": k2})
    balance_after_end = w3.eth.get_balance(k1)
    # Beneficiary receives the highest bid
    assert balance_after_end == balance_before_end + 1 * 10**10
    # Bidder cannot bid after auction end time has been reached
    with tx_failed():
        auction_contract.bid(transact={"value": 10, "from": k1})
    # Auction cannot be ended twice
    with tx_failed():
        auction_contract.endAuction()

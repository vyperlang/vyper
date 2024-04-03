import pytest

EXPIRY = 16


@pytest.fixture
def auction_start(revm_env):
    return revm_env.get_block("latest").timestamp + 1


@pytest.fixture
def auction_contract(revm_env, get_contract, auction_start, initial_balance):
    with open("examples/auctions/simple_open_auction.vy") as f:
        contract_code = f.read()

    for acc in revm_env.accounts[1:5]:
        revm_env.set_balance(acc, initial_balance)

    return get_contract(contract_code, *[revm_env.accounts[0], auction_start, EXPIRY])


def test_initial_state(revm_env, auction_contract, auction_start):
    # Check beneficiary is correct
    assert auction_contract.beneficiary() == revm_env.accounts[0]
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
    assert auction_contract.auctionEnd() >= revm_env.get_block("latest").timestamp


def test_bid(revm_env, auction_contract, tx_failed):
    k1, k2, k3, k4, k5 = revm_env.accounts[:5]
    revm_env.mine(1)  # make sure auction has started

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

    balance_before_withdrawal = revm_env.get_balance(k1)
    auction_contract.withdraw(transact={"from": k1})
    balance_after_withdrawal = revm_env.get_balance(k1)
    # Balance increases after withdrawal
    assert balance_after_withdrawal > balance_before_withdrawal
    # Pending return balance is reset to 0
    assert auction_contract.pendingReturns(k1) == 0


def test_end_auction(revm_env, auction_contract, tx_failed):
    k1, k2, k3, k4, k5 = revm_env.accounts[:5]

    revm_env.mine(1)  # make sure auction has started

    # Fails if auction end time has not been reached
    with tx_failed():
        auction_contract.endAuction()

    auction_contract.bid(transact={"value": 1 * 10**10, "from": k2})
    # Move block timestamp forward to reach auction end time
    # tester.time_travel(tester.get_block_by_number('latest')['timestamp'] + EXPIRY)
    revm_env.mine(EXPIRY)
    balance_before_end = revm_env.get_balance(k1)
    auction_contract.endAuction(transact={"from": k2})
    balance_after_end = revm_env.get_balance(k1)
    # Beneficiary receives the highest bid
    assert balance_after_end == balance_before_end + 1 * 10**10
    # Bidder cannot bid after auction end time has been reached
    with tx_failed():
        auction_contract.bid(transact={"value": 10, "from": k1})
    # Auction cannot be ended twice
    with tx_failed():
        auction_contract.endAuction()

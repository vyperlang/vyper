import pytest

from tests.utils import ZERO_ADDRESS

EXPIRY = 16


@pytest.fixture(scope="module")
def auction_start(env):
    return env.timestamp + 1


@pytest.fixture(scope="module")
def auction_contract(env, get_contract, auction_start):
    with open("examples/auctions/simple_open_auction.vy") as f:
        contract_code = f.read()

    for acc in env.accounts[:5]:
        env.set_balance(acc, 10**20)

    env.timestamp += 1  # make sure auction has started
    return get_contract(contract_code, *[env.accounts[0], auction_start, EXPIRY])


def test_initial_state(env, auction_contract, auction_start):
    # Check beneficiary is correct
    assert auction_contract.beneficiary() == env.accounts[0]
    # Check start time is `auction_start`
    assert auction_contract.auctionStart() == auction_start
    # Check time difference between start time and end time is EXPIRY
    assert auction_contract.auctionEnd() == auction_contract.auctionStart() + EXPIRY
    # Check auction has not ended
    assert auction_contract.ended() is False
    # Check highest bidder is empty
    assert auction_contract.highestBidder() == ZERO_ADDRESS
    # Check highest bid is 0
    assert auction_contract.highestBid() == 0
    # Check end time is more than current block timestamp
    assert auction_contract.auctionEnd() >= env.timestamp


def test_bid(env, auction_contract, tx_failed):
    k1, k2, k3, k4, k5 = env.accounts[:5]

    # Bidder cannot bid 0
    with tx_failed():
        auction_contract.bid(value=0, sender=k1)

    # Bidder can bid
    auction_contract.bid(value=1, sender=k1)
    # Check that highest bidder and highest bid have changed accordingly
    assert auction_contract.highestBidder() == k1
    assert auction_contract.highestBid() == 1
    # Bidder bid cannot equal current highest bid
    with tx_failed():
        auction_contract.bid(value=1, sender=k1)
    # Higher bid can replace current highest bid
    auction_contract.bid(value=2, sender=k2)
    # Check that highest bidder and highest bid have changed accordingly
    assert auction_contract.highestBidder() == k2
    assert auction_contract.highestBid() == 2
    # Multiple bidders can bid
    auction_contract.bid(value=3, sender=k3)
    auction_contract.bid(value=4, sender=k4)
    auction_contract.bid(value=5, sender=k5)
    # Check that highest bidder and highest bid have changed accordingly
    assert auction_contract.highestBidder() == k5
    assert auction_contract.highestBid() == 5
    auction_contract.bid(value=1 * 10**10, sender=k1)
    pending_return_before_outbid = auction_contract.pendingReturns(k1)
    auction_contract.bid(value=2 * 10**10, sender=k2)
    pending_return_after_outbid = auction_contract.pendingReturns(k1)
    # Account has a greater pending return balance after being outbid
    assert pending_return_after_outbid > pending_return_before_outbid

    balance_before_withdrawal = env.get_balance(k1)
    auction_contract.withdraw(sender=k1)
    balance_after_withdrawal = env.get_balance(k1)
    # Balance increases after withdrawal
    assert balance_after_withdrawal > balance_before_withdrawal
    # Pending return balance is reset to 0
    assert auction_contract.pendingReturns(k1) == 0


def test_end_auction(env, auction_contract, tx_failed):
    k1, k2, k3, k4, k5 = env.accounts[:5]

    # Fails if auction end time has not been reached
    with tx_failed():
        auction_contract.endAuction()

    auction_contract.bid(value=1 * 10**10, sender=k2)
    # Move block timestamp forward to reach auction end time
    env.timestamp += EXPIRY
    balance_before_end = env.get_balance(k1)
    auction_contract.endAuction(sender=k2)
    balance_after_end = env.get_balance(k1)
    # Beneficiary receives the highest bid
    assert balance_after_end == balance_before_end + 1 * 10**10
    # Bidder cannot bid after auction end time has been reached
    with tx_failed():
        auction_contract.bid(value=10, sender=k1)
    # Auction cannot be ended twice
    with tx_failed():
        auction_contract.endAuction()

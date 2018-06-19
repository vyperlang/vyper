import pytest

EXPIRY = 16


@pytest.fixture
def auction_contract(w3, get_contract):
    with open('examples/auctions/simple_open_auction.vy') as f:
        contract_code = f.read()
        contract = get_contract(contract_code, *[w3.eth.accounts[0], EXPIRY])
    return contract


def test_initial_state(w3, tester, auction_contract):
    # Check beneficiary is correct
    assert auction_contract.beneficiary() == w3.eth.accounts[0]
    # Check bidding time is 5 days
    assert auction_contract.auction_end() == tester.get_block_by_number('latest')['timestamp'] + EXPIRY
    # Check start time is current block timestamp
    assert auction_contract.auction_start() == tester.get_block_by_number('latest')['timestamp']
    # Check auction has not ended
    assert auction_contract.ended() is False
    # Check highest bidder is empty
    assert auction_contract.highest_bidder() is None
    # Check highest bid is 0
    assert auction_contract.highest_bid() == 0


def test_bid(w3, tester, auction_contract, assert_tx_failed):
    k1, k2, k3, k4, k5 = w3.eth.accounts[:5]
    # Bidder cannot bid 0
    assert_tx_failed(lambda: auction_contract.bid(transact={"value": 0, "from": k1}))
    # Bidder can bid
    auction_contract.bid(transact={"value": 1, "from": k1})
    # Check that higest bidder and highest bid have changed accordingly
    assert auction_contract.highest_bidder() == k1
    assert auction_contract.highest_bid() == 1
    # Bidder bid cannot equal current highest bid
    assert_tx_failed(lambda: auction_contract.bid(transact={"value": 0, "from": k1}))
    # Higher bid can replace current highest bid
    auction_contract.bid(transact={"value": 2, "from": k2})
    # Check that higest bidder and highest bid have changed accordingly
    assert auction_contract.highest_bidder() == k2
    assert auction_contract.highest_bid() == 2
    # Multiple bidders can bid
    auction_contract.bid(transact={"value": 3, "from": k3})
    auction_contract.bid(transact={"value": 4, "from": k4})
    auction_contract.bid(transact={"value": 5, "from": k5})
    # Check that higest bidder and highest bid have changed accordingly
    assert auction_contract.highest_bidder() == k5
    assert auction_contract.highest_bid() == 5
    auction_contract.bid(transact={"value": 1 * 10**10, "from": k1})
    balance_before_out_bid = w3.eth.getBalance(k1)
    auction_contract.bid(transact={"value": 2 * 10**10, "from": k2})
    balance_after_out_bid = w3.eth.getBalance(k1)
    # Account has more money after its bid is out bid
    assert balance_after_out_bid > balance_before_out_bid


def test_end_auction(w3, tester, auction_contract, assert_tx_failed):
    k1, k2, k3, k4, k5 = w3.eth.accounts[:5]
    # Fails if auction end time has not been reached
    assert_tx_failed(lambda: auction_contract.end_auction())
    auction_contract.bid(transact={"value": 1 * 10**10, "from": k2})
    # Move block timestamp foreward to reach auction end time
    # tester.time_travel(tester.get_block_by_number('latest')['timestamp'] + EXPIRY)
    w3.testing.mine(EXPIRY)
    balance_before_end = w3.eth.getBalance(k1)
    auction_contract.end_auction(transact={"from": k2})
    balance_after_end = w3.eth.getBalance(k1)
    # Beneficiary receives the highest bid
    assert balance_after_end == balance_before_end + 1 * 10 ** 10
    # Bidder cannot bid after auction end time has been reached
    assert_tx_failed(lambda: auction_contract.bid(transact={"value": 10, "from": k1}))
    # Auction cannot be ended twice
    assert_tx_failed(lambda: auction_contract.end_auction())

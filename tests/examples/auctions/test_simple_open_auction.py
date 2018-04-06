import pytest
import ethereum.utils as utils

FIVE_DAYS = 5 * 24 * 60 * 60


@pytest.fixture
def auction_contract(w3, get_contract):
    contract_code = open('examples/auctions/simple_open_auction.v.py').read()
    contract = get_contract(contract_code, *[w3.eth.accounts[0], FIVE_DAYS])
    return contract


def test_initial_state(w3, auction_contract):
    # Check beneficiary is correct
    assert '0x' + utils.remove_0x_head(auction_contract.beneficiary()) == w3.eth.accounts[0]
    # Check bidding time is 5 days
    assert auction_contract.auction_end() == auction_tester.s.head_state.timestamp + 432000
    # Check start time is current block timestamp
    assert auction_contract.auction_start() == auction_tester.s.head_state.timestamp
    # Check auction has not ended
    assert auction_contract.ended() is False
    # Check highest bidder is empty
    assert auction_contract.highest_bidder() == '0x0000000000000000000000000000000000000000'
    # Check highest bid is 0
    assert auction_contract.highest_bid() == 0


def test_bid(w3, auction_contract, assert_tx_failed):
    # auction_tester.s.mine()
    # Bidder cannot bid 0
    import ipdb; ipdb.set_trace()
    assert_tx_failed(lambda: auction_contract.bid(value=0, sender=auction_tester.k1))
    # Bidder can bid
    auction_contract.bid(value=1, sender=auction_tester.k1)
    # Check that higest bidder and highest bid have changed accordingly
    assert utils.remove_0x_head(auction_contract.highest_bidder()) == w3.eth.accounts[1].hex()
    assert auction_contract.highest_bid() == 1
    # Bidder bid cannot equal current highest bid
    assert_tx_failed(lambda: auction_contract.bid(value=1, sender=auction_tester.k1))
    # Higher bid can replace current highest bid
    auction_contract.bid(value=2, sender=auction_tester.k2)
    # Check that higest bidder and highest bid have changed accordingly
    assert utils.remove_0x_head(auction_contract.highest_bidder()) == w3.eth.accounts[2].hex()
    assert auction_contract.highest_bid() == 2
    # Multiple bidders can bid
    auction_contract.bid(value=3, sender=auction_tester.k3)
    auction_contract.bid(value=4, sender=auction_tester.k4)
    auction_contract.bid(value=5, sender=auction_tester.k5)
    # Check that higest bidder and highest bid have changed accordingly
    assert utils.remove_0x_head(auction_contract.highest_bidder()) == w3.eth.accounts[5].hex()
    assert auction_contract.highest_bid() == 5
    auction_contract.bid(value=1 * 10**10, sender=auction_tester.k1)
    balance_before_out_bid = auction_tester.s.head_state.get_balance(w3.eth.accounts[1])
    auction_contract.bid(value=2 * 10**10, sender=auction_tester.k2)
    balance_after_out_bid = auction_tester.s.head_state.get_balance(w3.eth.accounts[1])
    # Account has more money after its bid is out bid
    assert balance_after_out_bid > balance_before_out_bid


def test_end_auction(w3, auction_contract, assert_tx_failed):
    # auction_tester.s.mine()
    # Fails if auction end time has not been reached
    assert_tx_failed(lambda: auction_contract.end_auction())
    auction_contract.bid(value=1 * 10**10, sender=auction_tester.k2)
    # Move block timestamp foreward to reach auction end time
    # auction_tester.s.head_state.timestamp += FIVE_DAYS
    balance_before_end = auction_tester.s.head_state.get_balance(w3.eth.accounts[0])
    auction_contract.end_auction(sender=auction_tester.k2)
    balance_after_end = auction_tester.s.head_state.get_balance(w3.eth.accounts[0])
    # Beneficiary receives the highest bid
    assert balance_after_end == balance_before_end + 1 * 10 ** 10
    # Bidder cannot bid after auction end time has been reached
    assert_tx_failed(lambda: auction_contract.bid(value=10, sender=auction_tester.k1))
    # Auction cannot be ended twice
    assert_tx_failed(lambda: auction_contract.end_auction())

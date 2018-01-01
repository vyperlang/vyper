import pytest
import ethereum.utils as utils

FIVE_DAYS = 432000


@pytest.fixture
def auction_tester(t):
    from viper import compiler
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/auctions/simple_open_auction.v.py').read()
    t.c = t.s.contract(contract_code, language='viper', args=[t.accounts[0], FIVE_DAYS])
    return t


def test_initial_state(auction_tester):
    # Check beneficiary is correct
    assert utils.remove_0x_head(auction_tester.c.get_beneficiary()) == auction_tester.accounts[0].hex()
    # Check bidding time is 5 days
    assert auction_tester.c.get_auction_end() == auction_tester.s.head_state.timestamp + 432000
    # Check start time is current block timestamp
    assert auction_tester.c.get_auction_start() == auction_tester.s.head_state.timestamp
    # Check auction has not ended
    assert not auction_tester.c.get_ended()
    # Check highest bidder is empty
    assert auction_tester.c.get_highest_bidder() == '0x0000000000000000000000000000000000000000'
    # Check highest bid is 0
    assert auction_tester.c.get_highest_bid() == 0


def test_bid(auction_tester, assert_tx_failed):
    auction_tester.s.mine()
    # Bidder cannot bid 0
    assert_tx_failed(lambda: auction_tester.c.bid(value=0, sender=auction_tester.k1))
    # Bidder can bid
    auction_tester.c.bid(value=1, sender=auction_tester.k1)
    # Check that higest bidder and highest bid have changed accordingly
    assert utils.remove_0x_head(auction_tester.c.get_highest_bidder()) == auction_tester.accounts[1].hex()
    assert auction_tester.c.get_highest_bid() == 1
    # Bidder bid cannot equal current highest bid
    assert_tx_failed(lambda: auction_tester.c.bid(value=1, sender=auction_tester.k1))
    # Higher bid can replace current highest bid
    auction_tester.c.bid(value=2, sender=auction_tester.k2)
    # Check that higest bidder and highest bid have changed accordingly
    assert utils.remove_0x_head(auction_tester.c.get_highest_bidder()) == auction_tester.accounts[2].hex()
    assert auction_tester.c.get_highest_bid() == 2
    # Multiple bidders can bid
    auction_tester.c.bid(value=3, sender=auction_tester.k3)
    auction_tester.c.bid(value=4, sender=auction_tester.k4)
    auction_tester.c.bid(value=5, sender=auction_tester.k5)
    # Check that higest bidder and highest bid have changed accordingly
    assert utils.remove_0x_head(auction_tester.c.get_highest_bidder()) == auction_tester.accounts[5].hex()
    assert auction_tester.c.get_highest_bid() == 5
    auction_tester.c.bid(value=1 * 10**10, sender=auction_tester.k1)
    balance_before_out_bid = auction_tester.s.head_state.get_balance(auction_tester.accounts[1])
    auction_tester.c.bid(value=2 * 10**10, sender=auction_tester.k2)
    balance_after_out_bid = auction_tester.s.head_state.get_balance(auction_tester.accounts[1])
    # Account has more money after its bid is out bid
    assert balance_after_out_bid > balance_before_out_bid


def test_auction_end(auction_tester, assert_tx_failed):
    auction_tester.s.mine()
    # Fails if auction end time has not been reached
    assert_tx_failed(lambda: auction_tester.c.auction_end())
    auction_tester.c.bid(value=1 * 10**10, sender=auction_tester.k2)
    # Move block timestamp foreward to reach auction end time
    auction_tester.s.head_state.timestamp += FIVE_DAYS
    balance_before_end = auction_tester.s.head_state.get_balance(auction_tester.accounts[0])
    auction_tester.c.auction_end(sender=auction_tester.k2)
    balance_after_end = auction_tester.s.head_state.get_balance(auction_tester.accounts[0])
    # Beneficiary receives the highest bid
    assert balance_after_end == balance_before_end + 1 * 10 ** 10
    # Bidder cannot bid after auction end time has been reached
    assert_tx_failed(lambda: auction_tester.c.bid(value=10, sender=auction_tester.k1))
    # Auction cannot be ended twice
    assert_tx_failed(lambda: auction_tester.c.auction_end())

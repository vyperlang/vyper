# Test for Safe Remote Purchase (https://github.com/ethereum/solidity/blob/develop/docs/solidity-by-example.rst) ported to viper and optimized

# Rundown of the transaction:
# 1. Seller posts item for sale and posts safety deposit of double the item value. Balance is 2*value.
# (1.1. Seller can reclaim deposit and close the sale as long as nothing was purchased.)
# 2. Buyer purchases item (value) plus posts an additional safety deposit (Item value). Balance is 4*value
# 3. Seller ships item
# 4. Buyer confirms receiving the item. Buyer's deposit (value) is returned. Seller's deposit (2*value) + items value is returned. Balance is 0.
import pytest
from ethereum.tools import tester
from ethereum import utils

contract_code = open("examples/safe_remote_purchase/safe_remote_purchase.v.py").read()
# Inital balance of accounts
INIT_BAL = 1000000000000000000000000


@pytest.fixture
def srp_tester():
    t = tester
    tester.s = t.Chain()
    from viper import compiler
    t.languages["viper"] = compiler.Compiler()
    return tester


@pytest.fixture
def check_balance(tester):
    # balance of a0 = seller, a1 = buyer
    sbal = tester.s.head_state.get_balance(tester.a0)
    bbal = tester.s.head_state.get_balance(tester.a1)
    return [sbal, bbal]


def test_initial_state(srp_tester, assert_tx_failed):
    assert check_balance(srp_tester) == [INIT_BAL, INIT_BAL]
    # Inital deposit has to be divisible by two
    assert_tx_failed(lambda: srp_tester.s.contract(contract_code, language="viper", args=[], value=1))
    # Seller puts item up for sale
    srp_tester.c = tester.s.contract(contract_code, language="viper", args=[], value=2)
    # Check that the seller is set correctly
    assert utils.remove_0x_head(srp_tester.c.get_seller()) == srp_tester.accounts[0].hex()
    # Check if item value is set correctly (Half of deposit)
    assert srp_tester.c.get_value() == 1
    # Check if unlocked() works correctly after initialization
    assert srp_tester.c.get_unlocked()
    # Check that sellers (and buyers) balance is correct
    assert check_balance(srp_tester) == [INIT_BAL - 2, INIT_BAL]


def test_abort(srp_tester, assert_tx_failed):
    srp_tester.c = srp_tester.s.contract(contract_code, language="viper", args=[], value=2)
    # Only sender can trigger refund
    assert_tx_failed(lambda: srp_tester.c.abort(sender=srp_tester.k2))
    # Refund works correctly
    srp_tester.c.abort(sender=srp_tester.k0)
    assert check_balance(srp_tester) == [INIT_BAL, INIT_BAL]
    # Purchase in process, no refund possible
    srp_tester.c = srp_tester.s.contract(contract_code, language="viper", args=[], value=2)
    srp_tester.c.purchase(value=2, sender=srp_tester.k1)
    assert_tx_failed(lambda: srp_tester.c.abort(sender=srp_tester.k0))


def test_purchase(srp_tester, assert_tx_failed):
    srp_tester.c = srp_tester.s.contract(contract_code, language="viper", args=[], value=2)
    # Purchase for too low/high price
    assert_tx_failed(lambda: srp_tester.c.purchase(value=1, sender=srp_tester.k1))
    assert_tx_failed(lambda: srp_tester.c.purchase(value=3, sender=srp_tester.k1))
    # Purchase for the correct price
    srp_tester.c.purchase(value=2, sender=srp_tester.k1)
    # Check if buyer is set correctly
    assert utils.remove_0x_head(srp_tester.c.get_buyer()) == srp_tester.accounts[1].hex()
    # Check if contract is locked correctly, should return False
    assert not srp_tester.c.get_unlocked()
    # Check balances, both deposits should have been deducted
    assert check_balance(srp_tester) == [INIT_BAL - 2, INIT_BAL - 2]
    # Allow nobody else to purchase
    assert_tx_failed(lambda: srp_tester.c.purchase(value=2, sender=srp_tester.k3))


def test_received(srp_tester, assert_tx_failed):
    srp_tester.c = srp_tester.s.contract(contract_code, language="viper", args=[], value=2)
    # Can only be called after purchase
    assert_tx_failed(lambda: srp_tester.c.received(sender=srp_tester.k1))
    # Purchase completed
    srp_tester.c.purchase(value=2, sender=srp_tester.k1)
    # Check that e.g. sender cannot trigger received
    assert_tx_failed(lambda: srp_tester.c.received(sender=srp_tester.k0))
    # Check if buyer can call receive
    srp_tester.c.received(sender=srp_tester.k1)
    # Final check if everything worked. 1 value has been transferred
    assert check_balance(srp_tester) == [INIT_BAL + 1, INIT_BAL - 1]

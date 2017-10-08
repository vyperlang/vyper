#Test for Safe Remote Purchase (https://github.com/ethereum/solidity/blob/develop/docs/solidity-by-example.rst) ported to viper and optimized

#Rundown of the transaction:
#1. Seller posts item for sale and posts safety deposit of double the item value. Balance is 2*value.
#(1.1. Seller can reclaim deposit and close the sale as long as nothing was purchased.)
#2. Buyer purchases item (value) plus posts an additional safety deposit (Item value). Balance is 4*value
#3. Seller ships item
#4. Buyer confirms receiving the item. Buyer's deposit (value) is returned. Seller's deposit (2*value) + items value is returned. Balance is 0.
import pytest
from ethereum.tools import tester 
from ethereum import utils

contract_code = open("examples/safe_remote_purchase/safe_remote_purchase.v.py").read()
@pytest.fixture
def srp_tester():
    t = tester
    tester.s = t.Chain()
    from viper import compiler
    t.languages["viper"] = compiler.Compiler()
    #tester.c = tester.s.contract(contract_code, language = "viper", args = [], value=10)
    return tester

@pytest.fixture

def assert_tx_failed():
    def assert_tx_failed(tester, function_to_test, exception = tester.TransactionFailed):
        initial_state = tester.s.snapshot()
        with pytest.raises(exception):
            function_to_test()
        tester.s.revert(initial_state)
    return assert_tx_failed

def test_initial_state(srp_tester, assert_tx_failed):
    #Inital deposit has to be divisible by two
    assert_tx_failed(srp_tester, lambda: srp_tester.s.contract(contract_code, language = "viper", args = [], value = 1))
    #Seller puts item up for sale
    srp_tester.c = tester.s.contract(contract_code, language = "viper", args = [], value=2)
    #Check that the seller is set correctly
    assert utils.remove_0x_head(srp_tester.c.get_seller()) == srp_tester.accounts[0].hex()
    #Check if item value is set correctly (Half of deposit)
    assert srp_tester.c.get_value() == 1
    #Check if unlocked() works correctly after initialization
    assert srp_tester.c.unlocked() == True
"""
def test_abort(srp_tester):
    
    #Check if unlocked
    assert 
    """
def test_purchase(srp_tester, assert_tx_failed):
    srp_tester.c = srp_tester.s.contract(contract_code, language = "viper", args = [], value=2)
    print(srp_tester.c.get_value())
    print(srp_tester.c.unlocked())
    #Purchase for too low/high price
    assert_tx_failed(srp_tester, lambda: srp_tester.c.purchase(value=1, sender=srp_tester.k2))
    assert_tx_failed(srp_tester, lambda: srp_tester.c.purchase(value=3, sender=srp_tester.k2))
    #Purchase for the correct price 
    srp_tester.c.purchase(value=2, sender=srp_tester.k2)
    #Check if buyer is set correctly
    assert utils.remove_0x_head(srp_tester.c.get_buyer()) == srp_tester.accounts[1].hex()
    #Check if contract is locked correctly
    assert srp_tester.c.unlocked() == false
    #Allow nobody else to purchase
    assert_tx_failed(srp_tester, lambda: srp_tester.c.purchase(value=2, sender=srp_tester.k3))

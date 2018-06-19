# Test for Safe Remote Purchase (https://github.com/ethereum/solidity/blob/develop/docs/solidity-by-example.rst) ported to vyper and optimized

# Rundown of the transaction:
# 1. Seller posts item for sale and posts safety deposit of double the item value. Balance is 2*value.
# (1.1. Seller can reclaim deposit and close the sale as long as nothing was purchased.)
# 2. Buyer purchases item (value) plus posts an additional safety deposit (Item value). Balance is 4*value
# 3. Seller ships item
# 4. Buyer confirms receiving the item. Buyer's deposit (value) is returned. Seller's deposit (2*value) + items value is returned. Balance is 0.
import pytest


# Inital balance of accounts
INIT_BAL_a0 = 1000000000000000000000000
INIT_BAL_a1 = 1000000000000000000000000


@pytest.fixture
def contract_code(get_contract):
    with open("examples/safe_remote_purchase/safe_remote_purchase.vy") as f:
        contract_code = f.read()
    return contract_code


@pytest.fixture
def check_balance(w3, tester):
    def check_balance():
        a0, a1 = w3.eth.accounts[:2]
        # balance of a1 = seller, a2 = buyer
        return w3.eth.getBalance(a0), w3.eth.getBalance(a1)
    return check_balance


def test_initial_state(w3, assert_tx_failed, get_contract, check_balance, contract_code):
    assert check_balance() == (INIT_BAL_a0, INIT_BAL_a1)
    # Inital deposit has to be divisible by two
    assert_tx_failed(lambda: get_contract(contract_code, value=13))
    # Seller puts item up for sale
    a0_pre_bal, a1_pre_bal = check_balance()
    c = get_contract(contract_code, value_in_eth=2)
    # Check that the seller is set correctly
    assert c.seller() == w3.eth.accounts[0]
    # Check if item value is set correctly (Half of deposit)
    assert c.value() == w3.toWei(1, 'ether')
    # Check if unlocked() works correctly after initialization
    assert c.unlocked() is True
    # Check that sellers (and buyers) balance is correct
    assert check_balance() == ((INIT_BAL_a0 - w3.toWei(2, 'ether')), INIT_BAL_a1)


def test_abort(w3, assert_tx_failed, check_balance, get_contract, contract_code):
    a0, a1, a2 = w3.eth.accounts[:3]
    c = get_contract(contract_code, value=2)
    # Only sender can trigger refund
    assert_tx_failed(lambda: c.abort(transact={'from': a2}))
    # Refund works correctly
    c.abort(transact={'from': a0, 'gasPrice': 0})
    assert check_balance() == (INIT_BAL_a0 - w3.toWei(2, 'ether'), INIT_BAL_a1)
    # Purchase in process, no refund possible
    c = get_contract(contract_code, value=2)
    c.purchase(transact={'value': 2, 'from': a1, 'gasPrice': 0})
    assert_tx_failed(lambda: c.abort(transact={'from': a0}))


def test_purchase(w3, get_contract, assert_tx_failed, check_balance, contract_code):
    a0, a1, a2, a3 = w3.eth.accounts[:4]
    init_bal_a0, init_bal_a1 = check_balance()
    c = get_contract(contract_code, value=2)
    # Purchase for too low/high price
    assert_tx_failed(lambda: c.purchase(transact={'value': 1, 'from': a1}))
    assert_tx_failed(lambda: c.purchase(transact={'value': 3, 'from': a1}))
    # Purchase for the correct price
    c.purchase(transact={'value': 2, 'from': a1, 'gasPrice': 0})
    # Check if buyer is set correctly
    assert c.buyer() == a1
    # Check if contract is locked correctly
    assert c.unlocked() is False
    # Check balances, both deposits should have been deducted
    assert check_balance() == (init_bal_a0 - 2, init_bal_a1 - 2)
    # Allow nobody else to purchase
    assert_tx_failed(lambda: c.purchase(transact={'value': 2, 'from': a3}))


def test_received(w3, get_contract, assert_tx_failed, check_balance, contract_code):
    a0, a1 = w3.eth.accounts[:2]
    init_bal_a0, init_bal_a1 = check_balance()
    c = get_contract(contract_code, value=2)
    # Can only be called after purchase
    assert_tx_failed(lambda: c.received(transact={'from': a1, 'gasPrice': 0}))
    # Purchase completed
    c.purchase(transact={'value': 2, 'from': a1, 'gasPrice': 0})
    # Check that e.g. sender cannot trigger received
    assert_tx_failed(lambda: c.received(transact={'from': a0, 'gasPrice': 0}))
    # Check if buyer can call receive
    c.received(transact={'from': a1, 'gasPrice': 0})
    # Final check if everything worked. 1 value has been transferred
    assert check_balance() == (init_bal_a0 + 1, init_bal_a1 - 1)

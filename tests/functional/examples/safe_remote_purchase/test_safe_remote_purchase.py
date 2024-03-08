# Test for Safe Remote Purchase
# (https://github.com/ethereum/solidity/blob/develop/docs/solidity-by-example.rst)
# ported to vyper and optimized

# Rundown of the transaction:
# 1. Seller posts item for sale and posts safety deposit of double the item
#    value. Balance is 2*value.
# (1.1. Seller can reclaim deposit and close the sale as long as nothing was purchased.)
# 2. Buyer purchases item (value) plus posts an additional safety deposit (Item
#    value). Balance is 4*value
# 3. Seller ships item
# 4. Buyer confirms receiving the item. Buyer's deposit (value) is returned.
#    Seller's deposit (2*value) + items value is returned. Balance is 0.
import pytest


@pytest.fixture
def contract_code(get_contract):
    with open("examples/safe_remote_purchase/safe_remote_purchase.vy") as f:
        contract_code = f.read()
    return contract_code


@pytest.fixture
def get_balance(w3):
    def get_balance():
        a0, a1 = w3.eth.accounts[:2]
        # balance of a1 = seller, a2 = buyer
        return w3.eth.get_balance(a0), w3.eth.get_balance(a1)

    return get_balance


def test_initial_state(w3, tx_failed, get_contract, get_balance, contract_code):
    # Initial deposit has to be divisible by two
    with tx_failed():
        get_contract(contract_code, value=13)
    # Seller puts item up for sale
    a0_pre_bal, a1_pre_bal = get_balance()
    c = get_contract(contract_code, value_in_eth=2)
    # Check that the seller is set correctly
    assert c.seller() == w3.eth.accounts[0]
    # Check if item value is set correctly (Half of deposit)
    assert c.value() == w3.to_wei(1, "ether")
    # Check if unlocked() works correctly after initialization
    assert c.unlocked() is True
    # Check that sellers (and buyers) balance is correct
    assert get_balance() == ((a0_pre_bal - w3.to_wei(2, "ether")), a1_pre_bal)


def test_abort(w3, tx_failed, get_balance, get_contract, contract_code):
    a0, a1, a2 = w3.eth.accounts[:3]

    a0_pre_bal, a1_pre_bal = get_balance()
    c = get_contract(contract_code, value=w3.to_wei(2, "ether"))
    assert c.value() == w3.to_wei(1, "ether")
    # Only sender can trigger refund
    with tx_failed():
        c.abort(transact={"from": a2})
    # Refund works correctly
    c.abort(transact={"from": a0})
    assert get_balance() == (a0_pre_bal, a1_pre_bal)
    # Purchase in process, no refund possible
    c = get_contract(contract_code, value=2)
    c.purchase(transact={"value": 2, "from": a1})
    with tx_failed():
        c.abort(transact={"from": a0})


def test_purchase(w3, get_contract, tx_failed, get_balance, contract_code):
    a0, a1, a2, a3 = w3.eth.accounts[:4]
    init_bal_a0, init_bal_a1 = get_balance()
    c = get_contract(contract_code, value=2)
    # Purchase for too low/high price
    with tx_failed():
        c.purchase(transact={"value": 1, "from": a1})
    with tx_failed():
        c.purchase(transact={"value": 3, "from": a1})
    # Purchase for the correct price
    c.purchase(transact={"value": 2, "from": a1})
    # Check if buyer is set correctly
    assert c.buyer() == a1
    # Check if contract is locked correctly
    assert c.unlocked() is False
    # Check balances, both deposits should have been deducted
    assert get_balance() == (init_bal_a0 - 2, init_bal_a1 - 2)
    # Allow nobody else to purchase
    with tx_failed():
        c.purchase(transact={"value": 2, "from": a3})


def test_received(w3, get_contract, tx_failed, get_balance, contract_code):
    a0, a1 = w3.eth.accounts[:2]
    init_bal_a0, init_bal_a1 = get_balance()
    c = get_contract(contract_code, value=2)
    # Can only be called after purchase
    with tx_failed():
        c.received(transact={"from": a1})
    # Purchase completed
    c.purchase(transact={"value": 2, "from": a1})
    # Check that e.g. sender cannot trigger received
    with tx_failed():
        c.received(transact={"from": a0})
    # Check if buyer can call receive
    c.received(transact={"from": a1})
    # Final check if everything worked. 1 value has been transferred
    assert get_balance() == (init_bal_a0 + 1, init_bal_a1 - 1)


def test_received_reentrancy(w3, get_contract, tx_failed, get_balance, contract_code):
    buyer_contract_code = """
interface PurchaseContract:

    def received(): nonpayable
    def purchase(): payable
    def unlocked() -> bool: view

purchase_contract: PurchaseContract


@deploy
def __init__(_purchase_contract: address):
    self.purchase_contract = PurchaseContract(_purchase_contract)


@payable
@external
def start_purchase():
    extcall self.purchase_contract.purchase(value=2)


@payable
@external
def start_received():
   extcall self.purchase_contract.received()


@external
@payable
def __default__():
    extcall self.purchase_contract.received()

    """

    a0 = w3.eth.accounts[0]
    c = get_contract(contract_code, value=2)
    buyer_contract = get_contract(buyer_contract_code, *[c.address])
    buyer_contract_address = buyer_contract.address
    init_bal_a0, init_bal_buyer_contract = (
        w3.eth.get_balance(a0),
        w3.eth.get_balance(buyer_contract_address),
    )
    # Start purchase
    buyer_contract.start_purchase(transact={"value": 4, "from": w3.eth.accounts[1], "gas": 100000})
    assert c.unlocked() is False
    assert c.buyer() == buyer_contract_address

    # Trigger "re-entry"
    buyer_contract.start_received(transact={"from": w3.eth.accounts[1], "gas": 100000})

    # Final check if everything worked. 1 value has been transferred
    assert w3.eth.get_balance(a0), w3.eth.get_balance(buyer_contract_address) == (
        init_bal_a0 + 1,
        init_bal_buyer_contract - 1,
    )

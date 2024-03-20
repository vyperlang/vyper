import pytest
from web3.exceptions import ValidationError

INITIAL_VALUE = 4


@pytest.fixture
def adv_storage_contract(w3, get_contract):
    with open("examples/storage/advanced_storage.vy") as f:
        contract_code = f.read()
        # Pass constructor variables directly to the contract
        contract = get_contract(contract_code, INITIAL_VALUE)
    return contract


def test_initial_state(adv_storage_contract):
    # Check if the constructor of the contract is set up properly
    assert adv_storage_contract.storedData() == INITIAL_VALUE


def test_failed_transactions(w3, adv_storage_contract, tx_failed):
    k1 = w3.eth.accounts[1]

    # Try to set the storage to a negative amount
    with tx_failed():
        adv_storage_contract.set(-10, transact={"from": k1})

    # Lock the contract by storing more than 100. Then try to change the value
    adv_storage_contract.set(150, transact={"from": k1})
    with tx_failed():
        adv_storage_contract.set(10, transact={"from": k1})

    # Reset the contract and try to change the value
    adv_storage_contract.reset(transact={"from": k1})
    adv_storage_contract.set(10, transact={"from": k1})
    assert adv_storage_contract.storedData() == 10

    # Assert a different exception (ValidationError for non-matching argument type)
    with tx_failed(ValidationError):
        adv_storage_contract.set("foo", transact={"from": k1})

    # Assert a different exception that contains specific text
    with tx_failed(ValidationError, "invocation failed due to improper number of arguments"):
        adv_storage_contract.set(1, 2, transact={"from": k1})


def test_events(w3, adv_storage_contract, get_logs):
    k1, k2 = w3.eth.accounts[:2]

    tx1 = adv_storage_contract.set(10, transact={"from": k1})
    tx2 = adv_storage_contract.set(20, transact={"from": k2})
    tx3 = adv_storage_contract.reset(transact={"from": k1})

    # Save DataChange logs from all three transactions
    logs1 = get_logs(tx1, adv_storage_contract, "DataChange")
    logs2 = get_logs(tx2, adv_storage_contract, "DataChange")
    logs3 = get_logs(tx3, adv_storage_contract, "DataChange")

    # Check log contents
    assert len(logs1) == 1
    assert logs1[0].args.value == 10

    assert len(logs2) == 1
    assert logs2[0].args.setter == k2

    assert not logs3  # tx3 does not generate a log

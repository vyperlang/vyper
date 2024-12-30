import pytest

INITIAL_VALUE = 4


@pytest.fixture(scope="module")
def storage_contract(get_contract):
    with open("examples/storage/storage.vy") as f:
        contract_code = f.read()
        # Pass constructor variables directly to the contract
        contract = get_contract(contract_code, INITIAL_VALUE)
    return contract


def test_initial_state(storage_contract):
    # Check if the constructor of the contract is set up properly
    assert storage_contract.storedData() == INITIAL_VALUE


def test_set(storage_contract):
    storage_contract.set(10)
    assert storage_contract.storedData() == 10  # Directly access storedData

    storage_contract.set(-5)
    assert storage_contract.storedData() == -5

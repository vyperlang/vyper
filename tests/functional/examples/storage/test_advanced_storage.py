import pytest
from eth.codecs.abi.exceptions import EncodeError

INITIAL_VALUE = 4


@pytest.fixture(scope="module")
def adv_storage_contract(get_contract):
    with open("examples/storage/advanced_storage.vy") as f:
        contract_code = f.read()
        # Pass constructor variables directly to the contract
        contract = get_contract(contract_code, INITIAL_VALUE)
    return contract


def test_initial_state(adv_storage_contract):
    # Check if the constructor of the contract is set up properly
    assert adv_storage_contract.storedData() == INITIAL_VALUE


def test_failed_transactions(env, adv_storage_contract, tx_failed):
    k1 = env.accounts[1]
    env.set_balance(k1, 10**18)

    # Try to set the storage to a negative amount
    with tx_failed():
        adv_storage_contract.set(-10, sender=k1)

    # Lock the contract by storing more than 100. Then try to change the value
    adv_storage_contract.set(150, sender=k1)
    with tx_failed():
        adv_storage_contract.set(10, sender=k1)

    # Reset the contract and try to change the value
    adv_storage_contract.reset(sender=k1)
    adv_storage_contract.set(10, sender=k1)
    assert adv_storage_contract.storedData() == 10

    # Assert a different exception (ValidationError for non-matching argument type)
    with tx_failed(EncodeError):
        adv_storage_contract.set("foo", sender=k1)

    # Assert a different exception that contains specific text
    with tx_failed(TypeError, "invocation failed due to improper number of arguments"):
        adv_storage_contract.set(1, 2, sender=k1)


def test_events(env, adv_storage_contract, get_logs):
    k1, k2 = env.accounts[:2]

    adv_storage_contract.set(10, sender=k1)
    (log1,) = get_logs(adv_storage_contract, "DataChange")
    adv_storage_contract.set(20, sender=k2)
    (log2,) = get_logs(adv_storage_contract, "DataChange")
    adv_storage_contract.reset(sender=k1)
    logs3 = get_logs(adv_storage_contract, "DataChange")

    # Check log contents
    assert log1.args.value == 10
    assert log2.args.setter == k2
    assert logs3 == []  # tx3 does not generate a log

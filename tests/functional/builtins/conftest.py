import pytest


@pytest.fixture(scope="module")
def get_contract(get_revm_contract):
    return get_revm_contract

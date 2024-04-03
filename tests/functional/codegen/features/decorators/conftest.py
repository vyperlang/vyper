import pytest


@pytest.fixture(scope="module")
def initial_balance():
    return 10**20

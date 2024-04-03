import pytest


@pytest.fixture(autouse=True)
def setup(memory_mocker):
    pass


@pytest.fixture(scope="module")
def initial_balance():
    return 10**20

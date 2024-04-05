import pytest


@pytest.fixture(autouse=True)
def set_initial_balance(env):
    # set the balance of the deployer so the tests can transfer funds
    env.set_balance(env.deployer, 10**20)

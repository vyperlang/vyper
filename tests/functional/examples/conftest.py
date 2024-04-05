import pytest


@pytest.fixture(autouse=True)
def setup(memory_mocker):
    pass


@pytest.fixture(autouse=True)
def set_initial_balance(env):
    env.set_balance(env.deployer, 10**20)

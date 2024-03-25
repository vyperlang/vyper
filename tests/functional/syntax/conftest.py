import pytest


@pytest.fixture(scope="module")
def get_contract(get_revm_contract):
    return get_revm_contract


@pytest.fixture(scope="module")
def deploy_blueprint_for(deploy_blueprint_revm):
    return deploy_blueprint_revm


@pytest.fixture(scope="module")
def get_logs(get_logs_revm):
    return get_logs_revm

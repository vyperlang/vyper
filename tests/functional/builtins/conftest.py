import pytest

from tests.revm.abi_contract import ABIContract


@pytest.fixture(scope="module")
def get_contract(get_revm_contract):
    return get_revm_contract


@pytest.fixture(scope="module")
def deploy_blueprint_for(deploy_blueprint_revm):
    return deploy_blueprint_revm


@pytest.fixture(scope="module")
def get_logs(revm_env):
    def get_logs(tx_result, c: ABIContract, event_name):
        logs = revm_env.evm.result.logs
        parsed_logs = [c.parse_log(log) for log in logs if c.address == log.address]
        return [log for log in parsed_logs if log.event == event_name]

    return get_logs

import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_gas_call():
    gas_call = """

def foo() -> num:
    return msg.gas
    """

    c = get_contract_with_gas_estimation(gas_call)

    assert c.foo(startgas = 50000) < 50000
    assert c.foo(startgas = 50000) > 25000
    print('Passed gas test')

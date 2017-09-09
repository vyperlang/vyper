import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_null_code():
    null_code = """
def foo():
    pass
    """
    c = get_contract_with_gas_estimation(null_code)
    c.foo()
    print('Successfully executed a null function')


def test_basic_code():
    basic_code = """

def foo(x: num) -> num:
    return x * 2

    """
    c = get_contract_with_gas_estimation(basic_code)
    assert c.foo(9) == 18
    print('Passed basic code test')

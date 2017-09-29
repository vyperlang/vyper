import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract

def test_exponents_with_nums():
    exp_code = """
def _num_exp(x: num, y: num) -> num:
    return x**y
    """

    c = get_contract(exp_code)
    assert c._num_exp(2,2) == 4
    assert c._num_exp(2,3) == 8
    assert c._num_exp(2,4) == 16
    assert c._num_exp(3,2) == 9
    assert c._num_exp(3,3) == 27
    assert c._num_exp(72,19) == 72**19


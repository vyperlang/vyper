import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract

def test_as_num256_with_negative_num(assert_compile_failed):
    code = """
@public
def foo() -> num256:
    return as_num256(1-2)
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_as_num256_with_negative_input(assert_tx_failed):
    code = """
@public
def foo(x: num) -> num256:
    return as_num256(x)
"""
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.foo(-1))

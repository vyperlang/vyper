import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_is_contract():
    contract_1 = """
def foo(arg1: address) -> bool:
    result = arg1.is_contract
    return result
"""

    contract_2 = """
def foo(arg1: address) -> bool:
    return arg1.is_contract
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    
    assert c1.foo(c1.address) == True
    assert c1.foo(c2.address) == True
    assert c1.foo(t.a1) == False
    assert c1.foo(t.a3) == False
    assert c2.foo(c1.address) == True
    assert c2.foo(c2.address) == True
    assert c2.foo(t.a1) == False
    assert c2.foo(t.a3) == False

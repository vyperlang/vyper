import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation_for_constants, get_contract


def test_constant_test():
    constant_test = """
@public
@constant
def foo() -> num:
    return 5
    """

    c = get_contract_with_gas_estimation_for_constants(constant_test)
    assert c.foo() == 5

    print("Passed constant function test")

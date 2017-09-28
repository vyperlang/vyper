import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_internal_test():
    internal_test = """
@internal
def a() -> num:
    return 5

def returnten() -> num:
    return self.a() * 2
    """

    c = get_contract(internal_test)
    assert c.returnten() == 10

    print("Passed internal function test")

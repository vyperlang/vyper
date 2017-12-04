import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_private_test():
    private_test_code = """
@private
def a() -> num:
    return 5

@public
def returnten() -> num:
    return self.a() * 2
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.returnten() == 10

    print("Passed private function test")

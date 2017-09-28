import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_comment_test():
    comment_test = """

def foo() -> num:
    # Returns 3
    return 3
    """

    c = get_contract_with_gas_estimation(comment_test)
    assert c.foo() == 3
    print('Passed comment test')

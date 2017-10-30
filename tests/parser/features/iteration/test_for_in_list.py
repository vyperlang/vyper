import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract
from viper.exceptions import TypeMismatchException


def test_basic_in_list():
    code = """
def data() -> num:
    s = [1, 2, 3, 4, 5, 6]
    for i in s:
        if i >= 3:
            return i
    return -1
    """

    c = get_contract(code)

    assert c.data() == 3


def test_basic_in_list():
    code = """
def data() -> num:
    for i in [3, 5, 7, 9]:
        if i > 5:
            return i
    return -1
    """

    c = get_contract(code)

    assert c.data() == 7

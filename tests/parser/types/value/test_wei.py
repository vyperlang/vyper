import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_test_wei():
    test_wei = """
def return_2_finney() -> wei_value:
    return as_wei_value(2, finney)

def return_3_finney() -> wei_value:
    return as_wei_value(2 + 1, finney)

def return_2p5_ether() -> wei_value:
    return as_wei_value(2.5, ether)

def return_3p5_ether() -> wei_value:
    return as_wei_value(2.5 + 1, ether)

def return_2pow64_wei() -> wei_value:
    return as_wei_value(18446744.073709551616, szabo)
    """

    c = get_contract_with_gas_estimation(test_wei)

    assert c.return_2_finney() == 2 * 10**15
    assert c.return_3_finney() == 3 * 10**15, c.return_3_finney()
    assert c.return_2p5_ether() == 2.5 * 10**18
    assert c.return_3p5_ether() == 3.5 * 10**18
    assert c.return_2pow64_wei() == 2**64

    print("Passed wei value literals test")

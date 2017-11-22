import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_augassign_test():
    augassign_test = """
@public
def augadd(x: num, y: num) -> num:
    z = x
    z += y
    return z

@public
def augmul(x: num, y: num) -> num:
    z = x
    z *= y
    return z

@public
def augsub(x: num, y: num) -> num:
    z = x
    z -= y
    return z

@public
def augdiv(x: num, y: num) -> num:
    z = x
    z /= y
    return z

@public
def augmod(x: num, y: num) -> num:
    z = x
    z %= y
    return z
    """

    c = get_contract_with_gas_estimation(augassign_test)

    assert c.augadd(5, 12) == 17
    assert c.augmul(5, 12) == 60
    assert c.augsub(5, 12) == -7
    assert c.augdiv(5, 12) == 0
    assert c.augmod(5, 12) == 5
    print('Passed aug-assignment test')

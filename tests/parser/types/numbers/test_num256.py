import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_num256_code():
    num256_code = """
def _num256_add(x: num256, y: num256) -> num256:
    return num256_add(x, y)

def _num256_sub(x: num256, y: num256) -> num256:
    return num256_sub(x, y)

def _num256_mul(x: num256, y: num256) -> num256:
    return num256_mul(x, y)

def _num256_div(x: num256, y: num256) -> num256:
    return num256_div(x, y)

def _num256_gt(x: num256, y: num256) -> bool:
    return num256_gt(x, y)

def _num256_ge(x: num256, y: num256) -> bool:
    return num256_ge(x, y)

def _num256_lt(x: num256, y: num256) -> bool:
    return num256_lt(x, y)

def _num256_le(x: num256, y: num256) -> bool:
    return num256_le(x, y)
    """

    c = get_contract_with_gas_estimation(num256_code)
    x = 126416208461208640982146408124
    y = 7128468721412412459

    assert c._num256_add(x, y) == x + y
    assert c._num256_sub(x, y) == x - y
    assert c._num256_sub(y, x) == 2**256 + y - x
    assert c._num256_mul(x, y) == x * y
    assert c._num256_mul(2**128, 2**128) == 0
    assert c._num256_div(x, y) == x // y
    assert c._num256_div(y, x) == 0
    assert c._num256_gt(x, y) is True
    assert c._num256_ge(x, y) is True
    assert c._num256_le(x, y) is False
    assert c._num256_lt(x, y) is False
    assert c._num256_gt(x, x) is False
    assert c._num256_ge(x, x) is True
    assert c._num256_le(x, x) is True
    assert c._num256_lt(x, x) is False
    assert c._num256_lt(y, x) is True

    print("Passed num256 operation tests")


def test_num_256_natural_operators():
    num256_code = """
def _num256_add(x: num256, y: num256) -> num256:
    return x + y

def _num256_sub(x: num256, y: num256) -> num256:
    return x - y

def _num256_mul(x: num256, y: num256) -> num256:
    return x * y

def _num256_div(x: num256, y: num256) -> num256:
    return x / y

def _num256_gt(x: num256, y: num256) -> bool:
    return x > y

def _num256_ge(x: num256, y: num256) -> bool:
    return x >= y

def _num256_lt(x: num256, y: num256) -> bool:
    return x < y

def _num256_le(x: num256, y: num256) -> bool:
    return x <= y
"""

    c = get_contract_with_gas_estimation(num256_code)
    x = 126416208461208640982146408124
    y = 7128468721412412459

    assert c._num256_add(x, y) == x + y
    assert c._num256_sub(x, y) == x - y
    assert c._num256_sub(y, x) == 2**256 + y - x
    assert c._num256_mul(x, y) == x * y
    assert c._num256_mul(2**128, 2**128) == 0
    assert c._num256_div(x, y) == x // y
    assert c._num256_div(y, x) == 0
    assert c._num256_gt(x, y) is True
    assert c._num256_ge(x, y) is True
    assert c._num256_le(x, y) is False
    assert c._num256_lt(x, y) is False
    assert c._num256_gt(x, x) is False
    assert c._num256_ge(x, x) is True
    assert c._num256_le(x, x) is True
    assert c._num256_lt(x, x) is False
    assert c._num256_lt(y, x) is True

import pytest
from ethereum.abi import ValueOutOfBounds
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract, assert_tx_failed


def test_num256_code(assert_tx_failed):
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

    c = get_contract(num256_code)
    x = 126416208461208640982146408124
    y = 7128468721412412459

    t.s = s
    NUM256_MAX = 2**256 -1  # Max possible num256 value
    assert c._num256_add(x, y) == x + y
    assert c._num256_add(0,y) == y
    assert c._num256_add(y,0) == y
    assert_tx_failed(t, lambda: c._num256_add(NUM256_MAX, NUM256_MAX))
    assert c._num256_sub(x, y) == x - y
    assert_tx_failed(t, lambda: c._num256_sub(y, x))
    assert c._num256_sub(0, 0) == 0
    assert c._num256_sub(NUM256_MAX, 0) == NUM256_MAX
    assert_tx_failed(t, lambda: c._num256_sub(1, 2))
    assert c._num256_sub(NUM256_MAX, 1) == NUM256_MAX - 1
    assert c._num256_mul(x, y) == x * y
    assert_tx_failed(t, lambda: c._num256_mul(NUM256_MAX, 2))
    assert c._num256_mul(NUM256_MAX, 0) == 0
    assert c._num256_mul(0, NUM256_MAX) == 0
    assert c._num256_div(x, y) == x // y
    assert_tx_failed(t, lambda: c._num256_div(NUM256_MAX, 0))
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


def test_num256_mod(assert_tx_failed):
    num256_code = """
def _num256_mod(x: num256, y: num256) -> num256:
    return num256_mod(x, y)

def _num256_addmod(x: num256, y: num256, z: num256) -> num256:
    return num256_addmod(x, y, z)

def _num256_mulmod(x: num256, y: num256, z: num256) -> num256:
    return num256_mulmod(x, y, z)
    """

    c = get_contract(num256_code)
    t.s = s

    assert c._num256_mod(3, 2) == 1
    assert c._num256_mod(34, 32) == 2
    assert c._num256_addmod(1, 2, 2) == 1
    assert c._num256_addmod(32, 2, 32) == 2
    assert c._num256_addmod((2**256) - 1, 0, 2) == 1
    assert_tx_failed(t, lambda: c._num256_addmod((2**256) - 1, 1, 1))
    assert c._num256_mulmod(3, 1, 2) == 1
    assert c._num256_mulmod(200, 3, 601) == 600
    assert c._num256_mulmod(2**255, 1, 3) == 2
    assert_tx_failed(t, lambda: c._num256_mulmod(2**255, 2, 1))


def test_num256_with_exponents(assert_tx_failed):
    exp_code = """
def _num256_exp(x: num256, y: num256) -> num256:
        return num256_exp(x,y)
    """

    c = get_contract(exp_code)
    t.s = s

    assert c._num256_exp(2, 0) == 1
    assert c._num256_exp(2, 1) == 2
    assert c._num256_exp(2, 3) == 8
    assert_tx_failed(t, lambda: c._num256_exp(2**128, 2))
    assert c._num256_exp(2**64, 2) == 2**128
    assert c._num256_exp(7**23, 3) == 7**69


def test_num256_to_num_casting(assert_tx_failed):
    code = """
def _num256_to_num(x: num(num256)) -> num:
    return x

def _num256_to_num_call(x: num256) -> num:
    return self._num256_to_num(x)

def built_in_conversion(x: num256) -> num:
    return as_num128(x)
    """

    c = get_contract(code)

    # Ensure uint256 function signature.
    assert c.translator.function_data['_num256_to_num']['encode_types'] == ['uint256']

    assert c._num256_to_num(1) == 1
    assert c._num256_to_num((2**127) - 1) == 2**127 - 1
    t.s = s
    assert_tx_failed(t, lambda: c._num256_to_num((2**128)) == 0)
    assert c._num256_to_num_call(1) == 1

    # Check that casting matches manual conversion
    assert c._num256_to_num_call(2**127 - 1) == c.built_in_conversion(2**127 - 1)

    # Pass in negative int.
    assert_tx_failed(t, lambda: c._num256_to_num(-1) != -1, ValueOutOfBounds)
    # Make sure it can't be coherced into a negative number.
    assert_tx_failed(t, lambda: c._num256_to_num_call(2**127))

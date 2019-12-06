from decimal import (
    Decimal,
)

import pytest

from vyper.exceptions import (
    TypeMismatchException,
)


def test_unary_sub_uint256_fail(assert_compile_failed, get_contract):
    code = """@public
def negate(a: uint256) -> uint256:
    return -(a)
    """
    assert_compile_failed(lambda: get_contract(code), exception=TypeMismatchException)


def test_unary_sub_int128_fail(get_contract, assert_tx_failed):
    code = """@public
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    # This test should revert on overflow condition
    assert_tx_failed(lambda: c.negate(-2**127))


@pytest.mark.parametrize("val", [-2**127+1, 0, 2**127-1])
def test_unary_sub_int128_pass(get_contract, val):
    code = """@public
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    assert c.negate(val) == -val


decimal_divisor = Decimal('1e10')
min_decimal = (-2**127 + 1) / decimal_divisor
max_decimal = (2**127 - 1) / decimal_divisor
@pytest.mark.parametrize("val", [min_decimal, 0, max_decimal])
def test_unary_sub_decimal_pass(get_contract, val):
    code = """@public
def negate(a: decimal) -> decimal:
    return -(a)
    """
    c = get_contract(code)
    assert c.negate(val) == -val

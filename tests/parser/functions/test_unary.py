from decimal import Decimal

import pytest

from vyper.exceptions import InvalidOperation


def test_unary_sub_uint256_fail(assert_compile_failed, get_contract):
    code = """@external
def negate(a: uint256) -> uint256:
    return -(a)
    """
    assert_compile_failed(lambda: get_contract(code), exception=InvalidOperation)


def test_unary_sub_int128_fail(get_contract, assert_tx_failed):
    code = """@external
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    # This test should revert on overflow condition
    assert_tx_failed(lambda: c.negate(-(2 ** 127)))


@pytest.mark.parametrize("val", [-(2 ** 127) + 1, 0, 2 ** 127 - 1])
def test_unary_sub_int128_pass(get_contract, val):
    code = """@external
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    assert c.negate(val) == -val


min_decimal = -(2 ** 127) + 1
max_decimal = 2 ** 127 - 1


@pytest.mark.parametrize("val", [min_decimal, 0, max_decimal])
def test_unary_sub_decimal_pass(get_contract, val):
    code = """@external
def negate(a: decimal) -> decimal:
    return -(a)
    """
    c = get_contract(code)
    assert c.negate(val) == -val


def test_negation_decimal(get_contract):
    code = """
a: constant(decimal) = 170141183460469231731687303715884105726.9999999999
b: constant(decimal) = -170141183460469231731687303715884105726.9999999999

@external
def foo() -> decimal:
    return -a

@external
def bar() -> decimal:
    return -b
    """

    c = get_contract(code)
    assert c.foo() == Decimal("-170141183460469231731687303715884105726.9999999999")
    assert c.bar() == Decimal("170141183460469231731687303715884105726.9999999999")


def test_negation_int128(get_contract):
    code = """
a: constant(int128) = -2**127

@external
def foo() -> int128:
    return -2**127

@external
def bar() -> int128:
    return -(a+1)
    """
    c = get_contract(code)
    assert c.foo() == -(2 ** 127)
    assert c.bar() == 2 ** 127 - 1

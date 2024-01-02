from decimal import Decimal

import pytest

from vyper.exceptions import InvalidOperation


def test_unary_sub_uint256_fail(assert_compile_failed, get_contract):
    code = """@external
def negate(a: uint256) -> uint256:
    return -(a)
    """
    assert_compile_failed(lambda: get_contract(code), exception=InvalidOperation)


def test_unary_sub_int128_fail(get_contract, tx_failed):
    code = """@external
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    # This test should revert on overflow condition
    with tx_failed():
        c.negate(-(2**127))


@pytest.mark.parametrize("val", [-(2**127) + 1, 0, 2**127 - 1])
def test_unary_sub_int128_pass(get_contract, val):
    code = """@external
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    assert c.negate(val) == -val


min_decimal = -(2**127) + 1
max_decimal = 2**127 - 1


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
a: constant(decimal) = 18707220957835557353007165858768422651595.9365500927
b: constant(decimal) = -18707220957835557353007165858768422651595.9365500927

@external
def foo() -> decimal:
    return -a

@external
def bar() -> decimal:
    return -b
    """

    c = get_contract(code)
    assert c.foo() == Decimal("-18707220957835557353007165858768422651595.9365500927")
    assert c.bar() == Decimal("18707220957835557353007165858768422651595.9365500927")


def test_negation_int128(get_contract):
    code = """
a: constant(int128) = min_value(int128)

@external
def bar() -> int128:
    return -(a+1)
    """
    c = get_contract(code)
    assert c.bar() == 2**127 - 1

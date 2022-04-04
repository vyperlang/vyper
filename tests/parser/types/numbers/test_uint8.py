import itertools as it

import pytest

from vyper.codegen.types import parse_integer_typeinfo


def test_exponent_base_zero(get_contract):
    code = """
@external
def foo(x: uint8) -> uint8:
    return 0 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 0
    assert c.foo(42) == 0
    assert c.foo(2 ** 8 - 1) == 0


def test_exponent_base_one(get_contract):
    code = """
@external
def foo(x: uint8) -> uint8:
    return 1 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(42) == 1
    assert c.foo(2 ** 8 - 1) == 1


@pytest.mark.parametrize("base,power", it.product(range(6), repeat=2))
def test_safe_exponentiation(get_contract, assert_tx_failed, base, power):
    code = f"""
@external
def _uint8_exponentiation_base(_power: uint8) -> uint8:
    return {base} ** _power

@external
def _uint8_exponentiation_power(_base: uint8) -> uint8:
    return _base ** {power}
    """

    c = get_contract(code)

    if 0 <= base ** power < 2 ** 8 - 1:
        # within bounds so ok
        assert c._uint8_exponentiation_base(power) == base ** power
        assert c._uint8_exponentiation_power(base) == base ** power
    else:
        # clamps on exponentiation
        assert_tx_failed(lambda: c._uint8_exponentiation_base(power))
        assert_tx_failed(lambda: c._uint8_exponentiation_power(base))


def test_uint8_code(assert_tx_failed, get_contract_with_gas_estimation):
    uint8_code = """
@external
def _uint8_add(x: uint8, y: uint8) -> uint8:
    return x + y

@external
def _uint8_sub(x: uint8, y: uint8) -> uint8:
    return x - y

@external
def _uint8_mul(x: uint8, y: uint8) -> uint8:
    return x * y

@external
def _uint8_div(x: uint8, y: uint8) -> uint8:
    return x / y

@external
def _uint8_gt(x: uint8, y: uint8) -> bool:
    return x > y

@external
def _uint8_ge(x: uint8, y: uint8) -> bool:
    return x >= y

@external
def _uint8_lt(x: uint8, y: uint8) -> bool:
    return x < y

@external
def _uint8_le(x: uint8, y: uint8) -> bool:
    return x <= y
    """

    c = get_contract_with_gas_estimation(uint8_code)
    x = 18
    y = 12

    uint8_MAX = 2 ** 8 - 1  # Max possible uint8 value
    assert c._uint8_add(x, y) == x + y
    assert c._uint8_add(0, y) == y
    assert c._uint8_add(y, 0) == y
    assert_tx_failed(lambda: c._uint8_add(uint8_MAX, uint8_MAX))
    assert c._uint8_sub(x, y) == x - y
    assert_tx_failed(lambda: c._uint8_sub(y, x))
    assert c._uint8_sub(0, 0) == 0
    assert c._uint8_sub(uint8_MAX, 0) == uint8_MAX
    assert_tx_failed(lambda: c._uint8_sub(1, 2))
    assert c._uint8_sub(uint8_MAX, 1) == uint8_MAX - 1
    assert c._uint8_mul(x, y) == x * y
    assert_tx_failed(lambda: c._uint8_mul(uint8_MAX, 2))
    assert c._uint8_mul(uint8_MAX, 0) == 0
    assert c._uint8_mul(0, uint8_MAX) == 0
    assert c._uint8_div(x, y) == x // y
    assert_tx_failed(lambda: c._uint8_div(uint8_MAX, 0))
    assert c._uint8_div(y, x) == 0
    assert_tx_failed(lambda: c._uint8_div(x, 0))
    assert c._uint8_gt(x, y) is True
    assert c._uint8_ge(x, y) is True
    assert c._uint8_le(x, y) is False
    assert c._uint8_lt(x, y) is False
    assert c._uint8_gt(x, x) is False
    assert c._uint8_ge(x, x) is True
    assert c._uint8_le(x, x) is True
    assert c._uint8_lt(x, x) is False
    assert c._uint8_lt(y, x) is True

    print("Passed uint8 operation tests")


def test_uint8_literal(get_contract_with_gas_estimation):
    modexper = """
@external
def test() -> uint8:
    o: uint8 = 64
    return o
    """

    c = get_contract_with_gas_estimation(modexper)
    assert c.test() == 64


def test_uint8_comparison(get_contract_with_gas_estimation):
    code = """
max_uint_8: public(uint8)

@external
def __init__():
    self.max_uint_8 = 255

@external
def max_lt() -> (bool):
  return 30 < self.max_uint_8

@external
def max_lte() -> (bool):
  return 30  <= self.max_uint_8

@external
def max_gte() -> (bool):
  return 30 >=  self.max_uint_8

@external
def max_gt() -> (bool):
  return 30 > self.max_uint_8

@external
def max_ne() -> (bool):
  return 30 != self.max_uint_8
    """

    c = get_contract_with_gas_estimation(code)

    assert c.max_lt() is True
    assert c.max_lte() is True
    assert c.max_gte() is False
    assert c.max_gt() is False
    assert c.max_ne() is True


# TODO: create a tests/parser/functions/test_convert_to_uint8.py file


@pytest.mark.parametrize("in_typ", ["int256", "uint256", "int128", "uint128"])
def test_uint8_convert_clamps(get_contract, assert_tx_failed, in_typ):
    code = f"""
@external
def conversion(_x: {in_typ}) -> uint8:
    return convert(_x, uint8)
    """

    c = get_contract(code)

    int_info = parse_integer_typeinfo(in_typ)

    if int_info.is_signed:
        # below bounds
        for val in [int_info.bounds[0], -(2 ** 127), -3232, -256, -1]:
            assert_tx_failed(lambda: c.conversion(val))

    # above bounds
    above_bounds = [256, 3000, 2 ** 126, int_info.bounds[1]]
    for val in above_bounds:
        assert_tx_failed(lambda: c.conversion(val))

    # within bounds
    for val in [0, 10, 25, 130, 255]:
        assert c.conversion(val) == val

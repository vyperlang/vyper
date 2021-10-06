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

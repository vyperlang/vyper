def test_exponent_base_zero(get_contract):
    code = """
@external
def foo(x: uint256) -> uint256:
    return 0 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 0
    assert c.foo(42) == 0
    assert c.foo(2 ** 256 - 1) == 0


def test_exponent_base_one(get_contract):
    code = """
@external
def foo(x: uint256) -> uint256:
    return 1 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(42) == 1
    assert c.foo(2 ** 256 - 1) == 1


def test_uint256_code(assert_tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_add(x: uint256, y: uint256) -> uint256:
    return x + y

@external
def _uint256_sub(x: uint256, y: uint256) -> uint256:
    return x - y

@external
def _uint256_mul(x: uint256, y: uint256) -> uint256:
    return x * y

@external
def _uint256_div(x: uint256, y: uint256) -> uint256:
    return x / y

@external
def _uint256_gt(x: uint256, y: uint256) -> bool:
    return x > y

@external
def _uint256_ge(x: uint256, y: uint256) -> bool:
    return x >= y

@external
def _uint256_lt(x: uint256, y: uint256) -> bool:
    return x < y

@external
def _uint256_le(x: uint256, y: uint256) -> bool:
    return x <= y
    """

    c = get_contract_with_gas_estimation(uint256_code)
    x = 126416208461208640982146408124
    y = 7128468721412412459

    uint256_MAX = 2 ** 256 - 1  # Max possible uint256 value
    assert c._uint256_add(x, y) == x + y
    assert c._uint256_add(0, y) == y
    assert c._uint256_add(y, 0) == y
    assert_tx_failed(lambda: c._uint256_add(uint256_MAX, uint256_MAX))
    assert c._uint256_sub(x, y) == x - y
    assert_tx_failed(lambda: c._uint256_sub(y, x))
    assert c._uint256_sub(0, 0) == 0
    assert c._uint256_sub(uint256_MAX, 0) == uint256_MAX
    assert_tx_failed(lambda: c._uint256_sub(1, 2))
    assert c._uint256_sub(uint256_MAX, 1) == uint256_MAX - 1
    assert c._uint256_mul(x, y) == x * y
    assert_tx_failed(lambda: c._uint256_mul(uint256_MAX, 2))
    assert c._uint256_mul(uint256_MAX, 0) == 0
    assert c._uint256_mul(0, uint256_MAX) == 0
    assert c._uint256_div(x, y) == x // y
    assert_tx_failed(lambda: c._uint256_div(uint256_MAX, 0))
    assert c._uint256_div(y, x) == 0
    assert_tx_failed(lambda: c._uint256_div(x, 0))
    assert c._uint256_gt(x, y) is True
    assert c._uint256_ge(x, y) is True
    assert c._uint256_le(x, y) is False
    assert c._uint256_lt(x, y) is False
    assert c._uint256_gt(x, x) is False
    assert c._uint256_ge(x, x) is True
    assert c._uint256_le(x, x) is True
    assert c._uint256_lt(x, x) is False
    assert c._uint256_lt(y, x) is True

    print("Passed uint256 operation tests")


def test_uint256_mod(assert_tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_mod(x: uint256, y: uint256) -> uint256:
    return x % y

@external
def _uint256_addmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_addmod(x, y, z)

@external
def _uint256_mulmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_mulmod(x, y, z)
    """

    c = get_contract_with_gas_estimation(uint256_code)

    assert c._uint256_mod(3, 2) == 1
    assert c._uint256_mod(34, 32) == 2
    assert_tx_failed(lambda: c._uint256_mod(3, 0))
    assert c._uint256_addmod(1, 2, 2) == 1
    assert c._uint256_addmod(32, 2, 32) == 2
    assert c._uint256_addmod((2 ** 256) - 1, 0, 2) == 1
    assert c._uint256_addmod(2 ** 255, 2 ** 255, 6) == 4
    assert_tx_failed(lambda: c._uint256_addmod(1, 2, 0))
    assert c._uint256_mulmod(3, 1, 2) == 1
    assert c._uint256_mulmod(200, 3, 601) == 600
    assert c._uint256_mulmod(2 ** 255, 1, 3) == 2
    assert c._uint256_mulmod(2 ** 255, 2, 6) == 4
    assert_tx_failed(lambda: c._uint256_mulmod(2, 2, 0))


def test_modmul(get_contract_with_gas_estimation):
    modexper = """
@external
def exponential(base: uint256, exponent: uint256, modulus: uint256) -> uint256:
    o: uint256 = convert(1, uint256)
    for i in range(256):
        o = uint256_mulmod(o, o, modulus)
        if bitwise_and(exponent, shift(convert(1, uint256), 255 - i)) != convert(0, uint256):
            o = uint256_mulmod(o, base, modulus)
    return o
    """

    c = get_contract_with_gas_estimation(modexper)
    assert c.exponential(3, 5, 100) == 43
    assert c.exponential(2, 997, 997) == 2


def test_uint256_literal(get_contract_with_gas_estimation):
    modexper = """
@external
def test() -> uint256:
    o: uint256 = 340282366920938463463374607431768211459
    return o
    """

    c = get_contract_with_gas_estimation(modexper)
    assert c.test() == 340282366920938463463374607431768211459


def test_uint256_comparison(get_contract_with_gas_estimation):
    code = """
max_uint_256: public(uint256)

@external
def __init__():
    self.max_uint_256 = 2*(2**255-1)+1

@external
def max_lt() -> (bool):
  return 30 < self.max_uint_256

@external
def max_lte() -> (bool):
  return 30  <= self.max_uint_256

@external
def max_gte() -> (bool):
  return 30 >=  self.max_uint_256

@external
def max_gt() -> (bool):
  return 30 > self.max_uint_256

@external
def max_ne() -> (bool):
  return 30 != self.max_uint_256
    """

    c = get_contract_with_gas_estimation(code)

    assert c.max_lt() is True
    assert c.max_lte() is True
    assert c.max_gte() is False
    assert c.max_gt() is False
    assert c.max_ne() is True

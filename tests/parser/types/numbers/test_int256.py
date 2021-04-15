from vyper.exceptions import OverflowException


def test_exponent_base_zero(get_contract):
    code = """
@external
def foo(x: int256) -> int256:
    return 0 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 0
    assert c.foo(-1) == 0
    assert c.foo(2 ** 255 - 1) == 0
    assert c.foo(-(2 ** 255)) == 0


def test_exponent_base_one(get_contract):
    code = """
@external
def foo(x: int256) -> int256:
    return 1 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(-1) == 1
    assert c.foo(2 ** 255 - 1) == 1
    assert c.foo(-(2 ** 255)) == 1


def test_exponent(get_contract, assert_tx_failed):
    code = """
@external
def foo(x: int256) -> int256:
    return 4 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 4
    assert c.foo(4) == 256
    assert c.foo(127) == 4 ** 127
    assert_tx_failed(lambda: c.foo(128))
    assert_tx_failed(lambda: c.foo(-1))
    assert_tx_failed(lambda: c.foo(-(2 ** 255)))


def test_num_divided_by_num(get_contract_with_gas_estimation):
    code = """
@external
def foo(inp: int256) -> int256:
    y: int256 = 5/inp
    return y
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo(2) == 2
    assert c.foo(5) == 1
    assert c.foo(10) == 0
    assert c.foo(50) == 0


def test_negative_nums(get_contract_with_gas_estimation):
    negative_nums_code = """
@external
def _negative_num() -> int256:
    return -1

@external
def _negative_exp() -> int256:
    return -(1+2)

@external
def _negative_exp_var() -> int256:
    a: int256 = 2
    return -(a+2)
    """

    c = get_contract_with_gas_estimation(negative_nums_code)
    assert c._negative_num() == -1
    assert c._negative_exp() == -3
    assert c._negative_exp_var() == -4


def test_num_bound(assert_tx_failed, get_contract_with_gas_estimation):
    num_bound_code = """
@external
def _num(x: int256) -> int256:
    return x

@external
def _num_add(x: int256, y: int256) -> int256:
    return x + y

@external
def _num_sub(x: int256, y: int256) -> int256:
    return x - y

@external
def _num_add3(x: int256, y: int256, z: int256) -> int256:
    return x + y + z

@external
def _num_max() -> int256:
    return  2 ** 255 -1

@external
def _num_min() -> int256:
    return -2**255
    """

    c = get_contract_with_gas_estimation(num_bound_code)

    NUM_MAX = 2 ** 255 - 1
    NUM_MIN = -(2 ** 255)
    assert c._num_add(NUM_MAX, 0) == NUM_MAX
    assert c._num_sub(NUM_MIN, 0) == NUM_MIN
    assert c._num_add(NUM_MAX - 1, 1) == NUM_MAX
    assert c._num_sub(NUM_MIN + 1, 1) == NUM_MIN
    assert_tx_failed(lambda: c._num_add(NUM_MAX, 1))
    assert_tx_failed(lambda: c._num_sub(NUM_MIN, 1))
    assert_tx_failed(lambda: c._num_add(NUM_MAX - 1, 2))
    assert_tx_failed(lambda: c._num_sub(NUM_MIN + 1, 2))
    assert c._num_max() == NUM_MAX
    assert c._num_min() == NUM_MIN

    assert_tx_failed(lambda: c._num_add3(NUM_MAX, 1, -1))
    assert c._num_add3(NUM_MAX, -1, 1) == NUM_MAX


def test_overflow_out_of_range(get_contract, assert_compile_failed):
    code = """
@external
def num_sub() -> int256:
    return 1-2**256
    """

    assert_compile_failed(lambda: get_contract(code), OverflowException)


def test_overflow_add(get_contract, assert_tx_failed):
    code = """
@external
def num_add(i: int256) -> int256:
    return (2**255-1) + i
    """
    c = get_contract(code)

    assert c.num_add(0) == 2 ** 255 - 1
    assert c.num_add(-1) == 2 ** 255 - 2

    assert_tx_failed(lambda: c.num_add(1))
    assert_tx_failed(lambda: c.num_add(2))


def test_overflow_add_vars(get_contract, assert_tx_failed):
    code = """
@external
def num_add(a: int256, b: int256) -> int256:
    return a + b
    """
    c = get_contract(code)

    assert_tx_failed(lambda: c.num_add(2 ** 255 - 1, 1))
    assert_tx_failed(lambda: c.num_add(1, 2 ** 255 - 1))


def test_overflow_sub_vars(get_contract, assert_tx_failed):
    code = """
@external
def num_sub(a: int256, b: int256) -> int256:
    return a - b
    """

    c = get_contract(code)

    assert c.num_sub(-(2 ** 255), -1) == (-(2 ** 255)) + 1
    assert_tx_failed(lambda: c.num_sub(-(2 ** 255), 1))


def test_overflow_mul_vars(get_contract, assert_tx_failed):
    code = """
@external
def num_mul(a: int256, b: int256) -> int256:
    return a * b
    """

    c = get_contract(code)

    assert c.num_mul(-(2 ** 255), 1) == -(2 ** 255)
    assert c.num_mul(2 ** 255 - 1, -1) == -(2 ** 255) + 1
    assert c.num_mul(-1, 2 ** 255 - 1) == -(2 ** 255) + 1
    assert_tx_failed(lambda: c.num_mul(2 ** 254, 2))
    assert_tx_failed(lambda: c.num_mul(-(2 ** 255), -1))
    assert_tx_failed(lambda: c.num_mul(-1, -(2 ** 255)))


def test_overflow_mul_left_literal(get_contract, assert_tx_failed):
    code = """
@external
def num_mul(b: int256) -> int256:
    return -1 * b
    """

    c = get_contract(code)

    assert c.num_mul(2 ** 255 - 1) == -(2 ** 255) + 1
    assert c.num_mul(-(2 ** 255) + 1) == 2 ** 255 - 1
    assert_tx_failed(lambda: c.num_mul(-(2 ** 255)))


def test_overflow_mul_right_literal(get_contract, assert_tx_failed):
    code = """
@external
def num_mul(a: int256) -> int256:
    return a * -2**255
    """

    c = get_contract(code)

    assert c.num_mul(1) == -(2 ** 255)
    assert_tx_failed(lambda: c.num_mul(-1))


def test_literal_int_division(get_contract):
    code = """
@external
def foo() -> int256:
    z: int256 = 5 / 2
    return z
    """

    c = get_contract(code)

    assert c.foo() == 2


def test_overflow_division(get_contract, assert_tx_failed):
    code = """
@external
def foo(a: int256, b: int256) -> int256:
    return a / b
    """

    c = get_contract(code)

    assert c.foo(2 ** 255 - 1, -1) == -(2 ** 255) + 1
    assert c.foo(-(2 ** 255), 1) == -(2 ** 255)
    assert_tx_failed(lambda: c.foo(-(2 ** 255), -1))


def test_overflow_division_left_literal(get_contract, assert_tx_failed):
    code = """
@external
def foo(b: int256) -> int256:
    return -2**255 / b
    """

    c = get_contract(code)

    assert c.foo(1) == -(2 ** 255)
    assert_tx_failed(lambda: c.foo(-1))


def test_overflow_division_right_literal(get_contract, assert_tx_failed):
    code = """
@external
def foo(a: int256) -> int256:
    return a / -1
    """

    c = get_contract(code)

    assert c.foo(2 ** 255 - 1) == -(2 ** 255) + 1
    assert_tx_failed(lambda: c.foo(-(2 ** 255)))


def test_negation(get_contract, assert_tx_failed):
    code = """
@external
def foo(a: int256) -> int256:
    return -a
    """

    c = get_contract(code)

    assert c.foo(2 ** 255 - 1) == -(2 ** 255) + 1
    assert c.foo(-1) == 1
    assert c.foo(1) == -1
    assert c.foo(0) == 0
    assert_tx_failed(lambda: c.foo(-(2 ** 255)))


def test_literal_negative_int(get_contract, assert_tx_failed):
    code = """
@external
def addition(a: int256) -> int256:
    return a + -1

@external
def subtraction(a: int256) -> int256:
    return a - -1
    """

    c = get_contract(code)

    assert c.addition(23) == 22
    assert c.subtraction(23) == 24

    assert c.addition(-23) == -24
    assert c.subtraction(-23) == -22

    assert c.addition(-(2 ** 255) + 1) == -(2 ** 255)
    assert c.subtraction(2 ** 255 - 2) == 2 ** 255 - 1

    assert_tx_failed(lambda: c.addition(-(2 ** 255)))
    assert_tx_failed(lambda: c.subtraction(2 ** 255 - 1))

from vyper.exceptions import TypeMismatchException, InvalidLiteralException
from decimal import Decimal


def test_exponents_with_nums(get_contract_with_gas_estimation):
    exp_code = """
@public
def _num_exp(x: int128, y: int128) -> int128:
    return x**y
    """

    c = get_contract_with_gas_estimation(exp_code)
    assert c._num_exp(2, 2) == 4
    assert c._num_exp(2, 3) == 8
    assert c._num_exp(2, 4) == 16
    assert c._num_exp(3, 2) == 9
    assert c._num_exp(3, 3) == 27
    assert c._num_exp(72, 19) == 72 ** 19


def test_num_divided_by_num(get_contract_with_gas_estimation):
    code = """
@public
def foo(inp: int128) -> int128:
    y: int128 = 5/inp
    return y
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo(2) == 2
    assert c.foo(5) == 1
    assert c.foo(10) == 0
    assert c.foo(50) == 0


def test_decimal_divided_by_num(get_contract_with_gas_estimation):
    code = """
@public
def foo(inp: decimal) -> decimal:
    y: decimal = inp/5.0
    return y
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo(Decimal('1')) == Decimal('0.2')
    assert c.foo(Decimal('.5')) == Decimal('0.1')
    assert c.foo(Decimal('.2')) == Decimal('.04')


def test_negative_nums(get_contract_with_gas_estimation):
    negative_nums_code = """
@public
def _negative_num() -> int128:
    return -1

@public
def _negative_exp() -> int128:
    return -(1+2)

@public
def _negative_exp_var() -> int128:
    a: int128 = 2
    return -(a+2)
    """

    c = get_contract_with_gas_estimation(negative_nums_code)
    assert c._negative_num() == -1
    assert c._negative_exp() == -3
    assert c._negative_exp_var() == -4


def test_exponents_with_units(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> int128(wei):
    a: int128(wei)
    b: int128
    c: int128(wei)
    a = 2
    b = 2
    c = a ** b
    return c
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 4


def test_num_bound(assert_tx_failed, get_contract_with_gas_estimation):
    num_bound_code = """
@public
def _num(x: int128) -> int128:
    return x

@public
def _num_add(x: int128, y: int128) -> int128:
    return x + y

@public
def _num_sub(x: int128, y: int128) -> int128:
    return x - y

@public
def _num_add3(x: int128, y: int128, z: int128) -> int128:
    return x + y + z

@public
def _num_max() -> int128:
    return  170141183460469231731687303715884105727   #  2**127 - 1

@public
def _num_min() -> int128:
    return -170141183460469231731687303715884105728   # -2**127
    """

    c = get_contract_with_gas_estimation(num_bound_code)

    NUM_MAX = 2**127 - 1
    NUM_MIN = -2**127
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


def test_invalid_unit_exponent(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo():
    a: int128(wei)
    b: int128(wei)
    c = a ** b
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatchException)


def test_overflow_out_of_range(get_contract, assert_compile_failed):
    code = """
@public
def num_sub() -> int128:
    return 1-2**256
    """

    assert_compile_failed(lambda: get_contract(code), InvalidLiteralException)


def test_overflow_add(get_contract, assert_tx_failed):
    code = """
@public
def num_add(i: int128) -> int128:
    return (2**127-1) + i
    """
    c = get_contract(code)

    assert c.num_add(0) == 2**127 - 1
    assert c.num_add(-1) == 2**127 - 2

    assert_tx_failed(lambda: c.num_add(1))
    assert_tx_failed(lambda: c.num_add(2))


def test_overflow_add_vars(get_contract, assert_tx_failed):
    code = """
@public
def num_add(a: int128, b: int128) -> int128:
    return a + b
    """
    c = get_contract(code)

    assert_tx_failed(lambda: c.num_add(2**127 - 1, 1))
    assert_tx_failed(lambda: c.num_add(1, 2**127 - 1))


def test_overflow_sub_vars(get_contract, assert_tx_failed):
    code = """
@public
def num_sub(a: int128, b: int128) -> int128:
    return a - b
    """

    c = get_contract(code)

    assert c.num_sub(-2**127, -1) == (-2**127) + 1
    assert_tx_failed(lambda: c.num_sub(-2**127, 1))


def test_overflow_mul_vars(get_contract, assert_tx_failed):
    code = """
@public
def num_mul(a: int128, b: int128) -> int128:
    return a * b
    """

    c = get_contract(code)

    assert c.num_mul(-2**127, 1) == -2**127
    assert_tx_failed(lambda: c.num_mul(2**126, 2))


def test_overflow_pow_vars(get_contract, assert_tx_failed):
    code = """
@public
def num_pow(a: int128, b: int128) -> int128:
    return a ** b
    """

    c = get_contract(code)

    assert c.num_pow(-2, 127) == (-2**127)
    assert c.num_pow(2, 126) == (2**126)
    assert_tx_failed(lambda: c.num_pow(2**126, 2))


def test_literal_int_division(get_contract):
    code = """
@public
def foo() -> int128:
    z: int128 = 5 / 2
    return z
    """

    c = get_contract(code)

    assert c.foo() == 2


def test_literal_int_division_return(get_contract, assert_compile_failed):
    code = """
@public
def test() -> decimal:
    return 5 / 2
    """

    assert_compile_failed(lambda: get_contract(code))

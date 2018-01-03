from viper.exceptions import TypeMismatchException


def test_exponents_with_nums(get_contract_with_gas_estimation):
    exp_code = """
@public
def _num_exp(x: num, y: num) -> num:
    return x**y
    """

    c = get_contract_with_gas_estimation(exp_code)
    assert c._num_exp(2, 2) == 4
    assert c._num_exp(2, 3) == 8
    assert c._num_exp(2, 4) == 16
    assert c._num_exp(3, 2) == 9
    assert c._num_exp(3, 3) == 27
    assert c._num_exp(72, 19) == 72 ** 19


def test_negative_nums(t, get_contract_with_gas_estimation, chain):
    negative_nums_code = """
@public
def _negative_num() -> num:
    return -1

@public
def _negative_exp() -> num:
    return -(1+2)
    """

    c = get_contract_with_gas_estimation(negative_nums_code)
    t.s = chain
    assert c._negative_num() == -1
    assert c._negative_exp() == -3


def test_exponents_with_units(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num(wei):
    a: num(wei)
    b: num
    c: num(wei)
    a = 2
    b = 2
    c = a ** b
    return c
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 4


def test_num_bound(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    num_bound_code = """
@public
def _num(x: num) -> num:
    return x

@public
def _num_add(x: num, y: num) -> num:
    return x + y

@public
def _num_sub(x: num, y: num) -> num:
    return x - y

@public
def _num_add3(x: num, y: num, z: num) -> num:
    return x + y + z

@public
def _num_max() -> num:
    return  170141183460469231731687303715884105727   #  2**127 - 1

@public
def _num_min() -> num:
    return -170141183460469231731687303715884105728   # -2**127
    """

    c = get_contract_with_gas_estimation(num_bound_code)

    t.s = chain
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
    a: num(wei)
    b: num(wei)
    c = a ** b
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatchException)

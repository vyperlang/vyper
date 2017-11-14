import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation


def test_init_argument_test():
    init_argument_test = """
moose: num
def __init__(_moose: num):
    self.moose = _moose

def returnMoose() -> num:
    return self.moose
    """

    c = get_contract_with_gas_estimation(init_argument_test, args=[5])
    assert c.returnMoose() == 5
    print('Passed init argument test')


def test_constructor_advanced_code():
    constructor_advanced_code = """
twox: num

def __init__(x: num):
    self.twox = x * 2

def get_twox() -> num:
    return self.twox
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code, args=[5])
    assert c.get_twox() == 10


def test_constructor_advanced_code2():
    constructor_advanced_code2 = """
comb: num

def __init__(x: num[2], y: bytes <= 3, z: num):
    self.comb = x[0] * 1000 + x[1] * 100 + len(y) * 10 + z

def get_comb() -> num:
    return self.comb
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code2, args=[[5,7], "dog", 8])
    assert c.get_comb() == 5738
    print("Passed advanced init argument tests")


def test_large_input_code():
    large_input_code = """
def foo(x: num) -> num:
    return 3
    """

    c = get_contract_with_gas_estimation(large_input_code)
    c.foo(1274124)
    c.foo(2**120)
    try:
        c.foo(2**130)
        success = True
    except:
        success = False
    assert not success


def test_large_input_code_2():
    large_input_code_2 = """
def __init__(x: num):
    y = x

def foo() -> num:
    return 5
    """

    c = get_contract_with_gas_estimation(large_input_code_2, args=[17], sender=t.k0, value=0)
    try:
        c = get_contract_with_gas_estimation(large_input_code_2, args=[2**130], sender=t.k0, value=0)
        success = True
    except:
        success = False
    assert not success

    print('Passed invalid input tests')

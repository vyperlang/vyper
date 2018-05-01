from ethereum.abi import ValueOutOfBounds


def test_init_argument_test(get_contract_with_gas_estimation):
    init_argument_test = """
moose: int128

@public
def __init__(_moose: int128):
    self.moose = _moose

@public
def returnMoose() -> int128:
    return self.moose
    """

    c = get_contract_with_gas_estimation(init_argument_test, args=[5])
    assert c.returnMoose() == 5
    print('Passed init argument test')


def test_constructor_advanced_code(get_contract_with_gas_estimation):
    constructor_advanced_code = """
twox: int128

@public
def __init__(x: int128):
    self.twox = x * 2

@public
def get_twox() -> int128:
    return self.twox
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code, args=[5])
    assert c.get_twox() == 10


def test_constructor_advanced_code2(get_contract_with_gas_estimation):
    constructor_advanced_code2 = """
comb: int128

@public
def __init__(x: int128[2], y: bytes[3], z: int128):
    self.comb = x[0] * 1000 + x[1] * 100 + len(y) * 10 + z

@public
def get_comb() -> int128:
    return self.comb
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code2, args=[[5, 7], "dog", 8])
    assert c.get_comb() == 5738
    print("Passed advanced init argument tests")


def test_large_input_code(get_contract_with_gas_estimation):
    large_input_code = """
@public
def foo(x: int128) -> int128:
    return 3
    """

    c = get_contract_with_gas_estimation(large_input_code)
    c.foo(1274124)
    c.foo(2**120)
    try:
        c.foo(2**130)
        success = True
    except ValueOutOfBounds:
        success = False
    assert not success


def test_large_input_code_2(t, get_contract_with_gas_estimation):
    large_input_code_2 = """
@public
def __init__(x: int128):
    y: int128 = x

@public
def foo() -> int128:
    return 5
    """

    get_contract_with_gas_estimation(large_input_code_2, args=[17], sender=t.k0, value=0)
    try:
        get_contract_with_gas_estimation(large_input_code_2, args=[2**130], sender=t.k0, value=0)
        success = True
    except ValueOutOfBounds:
        success = False
    assert not success

    print('Passed invalid input tests')

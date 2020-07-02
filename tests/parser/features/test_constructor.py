import pytest
from web3.exceptions import ValidationError


def test_init_argument_test(get_contract_with_gas_estimation):
    init_argument_test = """
moose: int128

@external
def __init__(_moose: int128):
    self.moose = _moose

@external
def returnMoose() -> int128:
    return self.moose
    """

    c = get_contract_with_gas_estimation(init_argument_test, *[5])
    assert c.returnMoose() == 5
    print("Passed init argument test")


def test_constructor_advanced_code(get_contract_with_gas_estimation):
    constructor_advanced_code = """
twox: int128

@external
def __init__(x: int128):
    self.twox = x * 2

@external
def get_twox() -> int128:
    return self.twox
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code, *[5])
    assert c.get_twox() == 10


def test_constructor_advanced_code2(get_contract_with_gas_estimation):
    constructor_advanced_code2 = """
comb: uint256

@external
def __init__(x: uint256[2], y: Bytes[3], z: uint256):
    self.comb = x[0] * 1000 + x[1] * 100 + len(y) * 10 + z

@external
def get_comb() -> uint256:
    return self.comb
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code2, *[[5, 7], b"dog", 8])
    assert c.get_comb() == 5738
    print("Passed advanced init argument tests")


def test_large_input_code(get_contract_with_gas_estimation):
    large_input_code = """
@external
def foo(x: int128) -> int128:
    return 3
    """

    c = get_contract_with_gas_estimation(large_input_code)
    c.foo(1274124)
    c.foo(2 ** 120)

    with pytest.raises(ValidationError):
        c.foo(2 ** 130)


def test_large_input_code_2(w3, get_contract_with_gas_estimation):
    large_input_code_2 = """
@external
def __init__(x: int128):
    y: int128 = x

@external
def foo() -> int128:
    return 5
    """

    get_contract_with_gas_estimation(large_input_code_2, *[17])

    with pytest.raises(TypeError):
        get_contract_with_gas_estimation(large_input_code_2, *[2 ** 130])

    print("Passed invalid input tests")

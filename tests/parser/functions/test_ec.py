import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, G1, G1_times_two, G1_times_three, \
    curve_order, negative_G1


def test_ecadd():
    ecadder = """
x3: num256[2]
y3: num256[2]

def _ecadd(x: num256[2], y: num256[2]) -> num256[2]:
    return ecadd(x, y)

def _ecadd2(x: num256[2], y: num256[2]) -> num256[2]:
    x2 = x
    y2 = [y[0], y[1]]
    return ecadd(x2, y2)

def _ecadd3(x: num256[2], y: num256[2]) -> num256[2]:
    self.x3 = x
    self.y3 = [y[0], y[1]]
    return ecadd(self.x3, self.y3)

    """
    c = get_contract_with_gas_estimation(ecadder)

    assert c._ecadd(G1, G1) == G1_times_two
    assert c._ecadd2(G1, G1_times_two) == G1_times_three
    assert c._ecadd3(G1, [0, 0]) == G1
    assert c._ecadd3(G1, negative_G1) == [0, 0]

def test_ecmul():
    ecmuller = """
x3: num256[2]
y3: num256

def _ecmul(x: num256[2], y: num256) -> num256[2]:
    return ecmul(x, y)

def _ecmul2(x: num256[2], y: num256) -> num256[2]:
    x2 = x
    y2 = y
    return ecmul(x2, y2)

def _ecmul3(x: num256[2], y: num256) -> num256[2]:
    self.x3 = x
    self.y3 = y
    return ecmul(self.x3, self.y3)

"""
    c = get_contract_with_gas_estimation(ecmuller)

    assert c._ecmul(G1, 0) == [0 ,0]
    assert c._ecmul(G1, 1) == G1
    assert c._ecmul(G1, 3) == G1_times_three
    assert c._ecmul(G1, curve_order - 1) == negative_G1
    assert c._ecmul(G1, curve_order) == [0, 0]

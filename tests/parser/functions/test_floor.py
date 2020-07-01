from decimal import Decimal


def test_floor(get_contract_with_gas_estimation):
    code = """
x: decimal

@external
def __init__():
    self.x = 504.0000000001

@external
def x_floor() -> int128:
    return floor(self.x)

@external
def foo() -> int128:
    return floor(1.9999999999)

@external
def fop() -> int128:
    return floor(1.0000000001)

@external
def foq() -> int128:
    return floor(170141183460469231731687303715884105726.0000000002)

@external
def fos() -> int128:
    return floor(0.0)

@external
def fot() -> int128:
    return floor(0.0000000001)

@external
def fou() -> int128:
    a: decimal = 305.0
    b: decimal = 100.0
    c: decimal = a / b
    return floor(c)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.x_floor() == 504
    assert c.foo() == 1
    assert c.fop() == 1
    assert c.foq() == 170141183460469231731687303715884105726
    assert c.fos() == 0
    assert c.fot() == 0
    assert c.fou() == 3


def test_floor_negative(get_contract_with_gas_estimation):
    code = """
x: decimal

@external
def __init__():
    self.x = -504.0000000001

@external
def x_floor() -> int128:
    return floor(self.x)

@external
def foo() -> int128:
    a: int128 = -65
    b: decimal = convert(a, decimal) / 10.0
    return floor(b)

@external
def fop() -> int128:
    return floor(-27.0)

@external
def foq() -> int128:
    return floor(-9000.0000000001)

@external
def fos() -> int128:
    return floor(-0.0000000001)

@external
def fot() -> int128:
    return floor(-170141183460469231731687303715884105727.0000000002)

@external
def fou() -> int128:
    a: decimal = -305.0
    b: decimal = 100.0
    c: decimal = a / b
    return floor(c)

@external
def floor_param(p: decimal) -> int128:
    return floor(p)
"""

    c = get_contract_with_gas_estimation(code)

    assert c.x_floor() == -505
    assert c.foo() == -7
    assert c.fop() == -27
    assert c.foq() == -9001
    assert c.fos() == -1
    assert c.fot() == -170141183460469231731687303715884105728
    assert c.fou() == -4
    assert c.floor_param(Decimal("-5.6")) == -6
    assert c.floor_param(Decimal("-0.0000000001")) == -1

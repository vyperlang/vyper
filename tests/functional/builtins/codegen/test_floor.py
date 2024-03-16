import math
from decimal import Decimal


def test_floor(get_contract_with_gas_estimation):
    code = """
x: decimal

@deploy
def __init__():
    self.x = 504.0000000001

@external
def x_floor() -> int256:
    return floor(self.x)

@external
def foo() -> int256:
    return floor(1.9999999999)

@external
def fop() -> int256:
    return floor(1.0000000001)

@external
def foq() -> int256:
    return floor(18707220957835557353007165858768422651595.9365500927)

@external
def fos() -> int256:
    return floor(0.0)

@external
def fot() -> int256:
    return floor(0.0000000001)

@external
def fou() -> int256:
    a: decimal = 305.0
    b: decimal = 100.0
    c: decimal = a / b
    return floor(c)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.x_floor() == 504
    assert c.foo() == 1
    assert c.fop() == 1
    assert c.foq() == math.floor(Decimal(2**167 - 1) / 10**10)
    assert c.fos() == 0
    assert c.fot() == 0
    assert c.fou() == 3


def test_floor_negative(get_contract_with_gas_estimation):
    code = """
x: decimal

@deploy
def __init__():
    self.x = -504.0000000001

@external
def x_floor() -> int256:
    return floor(self.x)

@external
def foo() -> int256:
    a: int128 = -65
    b: decimal = convert(a, decimal) / 10.0
    return floor(b)

@external
def fop() -> int256:
    return floor(-27.0)

@external
def foq() -> int256:
    return floor(-9000.0000000001)

@external
def fos() -> int256:
    return floor(-0.0000000001)

@external
def fot() -> int256:
    return floor(-18707220957835557353007165858768422651595.9365500928)

@external
def fou() -> int256:
    a: decimal = -305.0
    b: decimal = 100.0
    c: decimal = a / b
    return floor(c)

@external
def floor_param(p: decimal) -> int256:
    return floor(p)
"""

    c = get_contract_with_gas_estimation(code)

    assert c.x_floor() == -505
    assert c.foo() == -7
    assert c.fop() == -27
    assert c.foq() == -9001
    assert c.fos() == -1
    assert c.fot() == math.floor(-Decimal(2**167) / 10**10)
    assert c.fou() == -4
    assert c.floor_param(Decimal("-5.6")) == -6
    assert c.floor_param(Decimal("-0.0000000001")) == -1


def test_floor_ext_call(w3, side_effects_contract, assert_side_effects_invoked, get_contract):
    code = """
interface Foo:
    def foo(x: decimal) -> decimal: nonpayable

@external
def foo(a: Foo) -> int256:
    return floor(extcall a.foo(2.5))
    """

    c1 = side_effects_contract("decimal")
    c2 = get_contract(code)

    assert c2.foo(c1.address) == 2

    assert_side_effects_invoked(c1, lambda: c2.foo(c1.address, transact={}))


def test_floor_internal_call(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> int256:
    return floor(self.bar())

@internal
def bar() -> decimal:
    return 2.5
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == 2

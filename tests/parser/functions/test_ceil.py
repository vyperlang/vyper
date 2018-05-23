from decimal import Decimal


def test_ceil(get_contract_with_gas_estimation):
    code = """
x: decimal

@public
def __init__():
    self.x = 504.0000000001

@public
def x_ceil() -> int128:
    return ceil(self.x)

@public
def foo() -> int128:
    return ceil(.9999999999)

@public
def fop() -> int128:
    return ceil(.0000000001)

@public
def foq() -> int128:
    return ceil(170141183460469231731687303715884105726.0000000002)

@public
def fos() -> int128:
    return ceil(0.0)

@public
def fou() -> int128:
    a: int128 = 305
    b: int128 = 100
    c: decimal = convert(a, 'decimal') / convert(b, 'decimal')
    return ceil(c)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.x_ceil() == 505
    assert c.foo() == 1
    assert c.fop() == 1
    assert c.foq() == 170141183460469231731687303715884105727
    assert c.fos() == 0
    assert c.fou() == 4


# ceil(x) should yeild the smallest integer greater than or equal to x
def test_ceil_negative(get_contract_with_gas_estimation):
    code = """
x: decimal

@public
def __init__():
    self.x = -504.0000000001

@public
def x_ceil() -> int128:
    return ceil(self.x)

@public
def foo() -> int128:
    return ceil(-11.01)

@public
def fop() -> int128:
    return ceil(-5.0)

@public
def foq() -> int128:
    return ceil(-.0000000001)

@public
def fos() -> int128:
    return ceil(-5472.9999999999)

@public
def fot() -> int128:
    return ceil(-170141183460469231731687303715884105727.0000000002)

@public
def fou() -> int128:
    a: decimal = -305.0
    b: decimal = 100.0
    c: decimal = a / b
    return ceil(c)

@public
def ceil_param(p: decimal) -> int128:
    return ceil(p)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.x_ceil() == -504
    assert c.foo() == -11
    assert c.fop() == -5
    assert c.foq() == 0
    assert c.fos() == -5472
    assert c.fot() == -170141183460469231731687303715884105727
    assert c.fou() == -3
    assert c.ceil_param(Decimal('-0.5')) == 0
    assert c.ceil_param(Decimal('-7777777.7777777')) == -7777777

def test_floor(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> int128:
    return floor(1.9999999999)

@public
def fop() -> int128:
    return floor(1.0000000001)

@public
def foq() -> int128:
    return floor(170141183460469231731687303715884105723.0000000001)

@public
def fos() -> int128:
    return floor(0.0)

@public
def fot() -> int128:
    return floor(0.0000000001)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 1
    assert c.fop() == 1
    assert c.foq() == 170141183460469231731687303715884105723
    assert c.fos() == 0
    assert c.fot() == 0


def test_floor_negative(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> int128:
    x: int128 = -65
    y: decimal = x / 10
    return floor(y)

@public
def fop() -> int128:
    return floor(-27.0)

@public
def foq() -> int128:
    return floor(-9000.0000000001)

@public
def fos() -> int128:
    return floor(-0.0000000001)

@public
def fot() -> int128:
    return floor(-170141183460469231731687303715884105727.0000000001)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == -7
    assert c.fop() == -27
    assert c.foq() == -9001
    assert c.fos() == -1
    assert c.fot() == -170141183460469231731687303715884105728

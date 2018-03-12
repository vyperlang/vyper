def test_ceil(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> int128:
    return ceil(.9999999999)

@public
def fop() -> int128:
    return ceil(.0000000001)

@public
def foq() -> int128:
    return ceil(170141183460469231731687303715884105723.0000000001)

@public
def fos() -> int128:
    return ceil(0.0)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 1
    assert c.fop() == 1
    assert c.foq() == 170141183460469231731687303715884105724
    assert c.fos() == 0


# ceil(x) should yeild the smallest integer greater than or equal to x
def test_ceil_negative(get_contract_with_gas_estimation):
    code = """
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
    return ceil(-170141183460469231731687303715884105727.0000000001)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == -11
    assert c.fop() == -5
    assert c.foq() == 0
    assert c.fos() == -5472
    assert c.fot() == -170141183460469231731687303715884105727

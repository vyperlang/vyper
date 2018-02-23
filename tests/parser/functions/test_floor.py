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
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 1
    assert c.fop() == 1
    assert c.foq() == 170141183460469231731687303715884105723

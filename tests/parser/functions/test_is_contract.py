def test_is_contract(t, get_contract_with_gas_estimation):
    contract_1 = """
@public
def foo(arg1: address) -> bool:
    result: bool = arg1.is_contract
    return result
"""

    contract_2 = """
@public
def foo(arg1: address) -> bool:
    return arg1.is_contract
"""
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.foo(c1.address) is True
    assert c1.foo(c2.address) is True
    assert c1.foo(t.a1) is False
    assert c1.foo(t.a3) is False
    assert c2.foo(c1.address) is True
    assert c2.foo(c2.address) is True
    assert c2.foo(t.a1) is False
    assert c2.foo(t.a3) is False

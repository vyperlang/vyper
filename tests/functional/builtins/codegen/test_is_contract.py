def test_is_contract(w3, get_contract_with_gas_estimation):
    contract_1 = """
@external
def foo(arg1: address) -> bool:
    result: bool = arg1.is_contract
    return result
"""

    contract_2 = """
@external
def foo(arg1: address) -> bool:
    return arg1.is_contract
"""
    a0, a1 = w3.eth.accounts[:2]
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.foo(c1.address) is True
    assert c1.foo(c2.address) is True
    assert c1.foo(a1) is False
    assert c1.foo(a0) is False
    assert c2.foo(c1.address) is True
    assert c2.foo(c2.address) is True
    assert c2.foo(a1) is False
    assert c2.foo(a0) is False

def test_gas_call(get_contract):
    gas_call = """
@external
def foo() -> uint256:
    return msg.gas
    """

    c = get_contract(gas_call)

    assert c.foo(gas=50000) < 50000
    assert c.foo(gas=50000) > 25000

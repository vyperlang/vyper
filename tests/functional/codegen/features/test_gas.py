def test_gas_call(get_contract_with_gas_estimation):
    gas_call = """
@external
def foo() -> uint256:
    return msg.gas
    """

    c = get_contract_with_gas_estimation(gas_call)

    assert c.foo(call={"gas": 50000}) < 50000
    assert c.foo(call={"gas": 50000}) > 25000

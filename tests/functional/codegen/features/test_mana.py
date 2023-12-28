def test_mana_call(get_contract_with_gas_estimation):
    mana_call = """
@external
def foo() -> uint256:
    return msg.mana
    """

    c = get_contract_with_gas_estimation(mana_call)

    assert c.foo(call={"gas": 50000}) < 50000
    assert c.foo(call={"gas": 50000}) > 25000

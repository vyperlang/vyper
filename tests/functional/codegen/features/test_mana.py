def test_mana_call(get_contract):
    mana_call = """
@external
def foo() -> uint256:
    return msg.mana
    """

    c = get_contract(mana_call)

    assert c.foo(gas=50000) < 50000
    assert c.foo(gas=50000) > 25000

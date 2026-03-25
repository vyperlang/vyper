def test_constant_address_balance(env, get_contract):
    code = """
a: constant(address) = 0x776Ba14735FF84789320718cf0aa43e91F7A8Ce1

@external
def foo() -> uint256:
    x: uint256 = a.balance
    return x
    """
    address = "0x776Ba14735FF84789320718cf0aa43e91F7A8Ce1"

    c = get_contract(code)

    assert c.foo() == 0

    env.set_balance(env.deployer, 1337)
    env.message_call(address, value=1337)

    assert c.foo() == 1337

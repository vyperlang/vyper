def test_ext_call(w3, side_effects_contract, assert_side_effects_invoked, get_contract):
    code = """
@external
def foo(addr: address) -> uint256:
    a: Foo = Foo(addr)

    return as_wei_value(a.foo(), "ether")

interface Foo:
    def foo() -> uint8: nonpayable
    """

    c1 = side_effects_contract("uint8", 7)
    c2 = get_contract(code)

    assert c2.foo(c1.address) == w3.to_wei(7, "ether")

    a0 = w3.eth.accounts[0]
    assert_side_effects_invoked(lambda: c2.foo(c1.address, transact={"from": a0}), c1)


def test_internal_call(w3, get_contract_with_gas_estimation):
    code = """
@external
def foo() -> uint256:
    return as_wei_value(self.bar(), "ether")

@internal
def bar() -> uint8:
    return 7
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == w3.to_wei(7, "ether")

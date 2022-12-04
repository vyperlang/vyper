def test_ext_call(w3, get_contract_with_gas_estimation):
    code1 = """
@external
def bar() -> uint8:
    return 7
    """

    code2 = """
@external
def foo(addr: address) -> uint256:
    a: Foo = Foo(addr)

    return as_wei_value(a.bar(), "ether")

interface Foo:
    def bar() -> uint8: nonpayable
    """

    c1 = get_contract_with_gas_estimation(code1)
    c2 = get_contract_with_gas_estimation(code2)

    assert c2.foo(c1.address) == w3.toWei(7, "ether")


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

    assert c.foo() == w3.toWei(7, "ether")

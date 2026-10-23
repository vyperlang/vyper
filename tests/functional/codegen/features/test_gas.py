def test_gas_call(get_contract):
    gas_call = """
@external
def foo() -> uint256:
    return msg.gas
    """

    c = get_contract(gas_call)

    assert c.foo(gas=50000) < 50000
    assert c.foo(gas=50000) > 25000


def test_gas_read_not_reordered_across_call(get_contract):
    # the callee burns most of its gas stipend
    burner = """
x: uint256

@external
def __default__():
    for i: uint256 in range(200):
        self.x += i
    """
    measure = """
@external
def measure(t: address) -> uint256:
    a: uint256 = msg.gas
    ok: bool = raw_call(t, b"", gas=100000, revert_on_failure=False)
    b: uint256 = msg.gas
    return a - b
    """
    b = get_contract(burner)
    c = get_contract(measure)
    # if either `msg.gas` read is moved across the call, this is ~5
    assert c.measure(b.address) > 50_000

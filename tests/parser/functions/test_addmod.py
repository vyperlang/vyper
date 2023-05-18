def test_uint256_addmod(assert_tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_addmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_addmod(x, y, z)
    """

    c = get_contract_with_gas_estimation(uint256_code)

    assert c._uint256_addmod(1, 2, 2) == 1
    assert c._uint256_addmod(32, 2, 32) == 2
    assert c._uint256_addmod((2**256) - 1, 0, 2) == 1
    assert c._uint256_addmod(2**255, 2**255, 6) == 4
    assert_tx_failed(lambda: c._uint256_addmod(1, 2, 0))


def test_uint256_addmod_ext_call(
    w3, side_effects_contract, assert_side_effects_invoked, get_contract
):
    code = """
@external
def foo(f: Foo) -> uint256:
    return uint256_addmod(32, 2, f.foo(32))

interface Foo:
    def foo(x: uint256) -> uint256: payable
    """

    c1 = side_effects_contract("uint256")
    c2 = get_contract(code)

    assert c2.foo(c1.address) == 2
    assert_side_effects_invoked(c1, lambda: c2.foo(c1.address, transact={}))


def test_uint256_addmod_internal_call(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> uint256:
    return uint256_addmod(self.a(), self.b(), self.c())

@internal
def a() -> uint256:
    return 32

@internal
def b() -> uint256:
    return 2

@internal
def c() -> uint256:
    return 32
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == 2

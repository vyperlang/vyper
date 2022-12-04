def test_uint256_addmod(assert_tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_addmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_addmod(x, y, z)
    """

    c = get_contract_with_gas_estimation(uint256_code)

    assert c._uint256_addmod(1, 2, 2) == 1
    assert c._uint256_addmod(32, 2, 32) == 2
    assert c._uint256_addmod((2 ** 256) - 1, 0, 2) == 1
    assert c._uint256_addmod(2 ** 255, 2 ** 255, 6) == 4
    assert_tx_failed(lambda: c._uint256_addmod(1, 2, 0))


def test_uint256_addmod_ext_call(get_contract_with_gas_estimation):
    code1 = """
@external
def a() -> uint256:
    return 32

@external
def b() -> uint256:
    return 2

@external
def c() -> uint256:
    return 32
    """

    code2 = """
@external
def foo(addr: address) -> uint256:
    f: Foo = Foo(addr)

    return uint256_addmod(f.a(), f.b(), f.c())

interface Foo:
    def a() -> uint256: nonpayable
    def b() -> uint256: nonpayable
    def c() -> uint256: nonpayable
    """

    c1 = get_contract_with_gas_estimation(code1)
    c2 = get_contract_with_gas_estimation(code2)

    assert c2.foo(c1.address) == 2


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

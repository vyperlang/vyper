def test_uint256_mulmod(assert_tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_mulmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_mulmod(x, y, z)
    """

    c = get_contract_with_gas_estimation(uint256_code)

    assert c._uint256_mulmod(3, 1, 2) == 1
    assert c._uint256_mulmod(200, 3, 601) == 600
    assert c._uint256_mulmod(2 ** 255, 1, 3) == 2
    assert c._uint256_mulmod(2 ** 255, 2, 6) == 4
    assert_tx_failed(lambda: c._uint256_mulmod(2, 2, 0))


def test_uint256_mulmod_complex(get_contract_with_gas_estimation):
    modexper = """
@external
def exponential(base: uint256, exponent: uint256, modulus: uint256) -> uint256:
    o: uint256 = 1
    for i in range(256):
        o = uint256_mulmod(o, o, modulus)
        if exponent & shift(1, 255 - i) != 0:
            o = uint256_mulmod(o, base, modulus)
    return o
    """

    c = get_contract_with_gas_estimation(modexper)
    assert c.exponential(3, 5, 100) == 43
    assert c.exponential(2, 997, 997) == 2


def test_uint256_mulmod_ext_call(get_contract_with_gas_estimation):
    code1 = """
@external
def a() -> uint256:
    return 200

@external
def b() -> uint256:
    return 3

@external
def c() -> uint256:
    return 601
    """

    code2 = """
@external
def foo(addr: address) -> uint256:
    f: Foo = Foo(addr)

    return uint256_mulmod(f.a(), f.b(), f.c())

interface Foo:
    def a() -> uint256: nonpayable
    def b() -> uint256: nonpayable
    def c() -> uint256: nonpayable
    """

    c1 = get_contract_with_gas_estimation(code1)
    c2 = get_contract_with_gas_estimation(code2)

    assert c2.foo(c1.address) == 600


def test_uint256_mulmod_internal_call(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> uint256:
    return uint256_mulmod(self.a(), self.b(), self.c())

@internal
def a() -> uint256:
    return 200

@internal
def b() -> uint256:
    return 3

@internal
def c() -> uint256:
    return 601
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == 600

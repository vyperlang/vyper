def test_uint256_mulmod(tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_mulmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_mulmod(x, y, z)
    """

    c = get_contract_with_gas_estimation(uint256_code)

    assert c._uint256_mulmod(3, 1, 2) == 1
    assert c._uint256_mulmod(200, 3, 601) == 600
    assert c._uint256_mulmod(2**255, 1, 3) == 2
    assert c._uint256_mulmod(2**255, 2, 6) == 4
    with tx_failed():
        c._uint256_mulmod(2, 2, 0)


def test_uint256_mulmod_complex(get_contract_with_gas_estimation):
    modexper = """
@external
def exponential(base: uint256, exponent: uint256, modulus: uint256) -> uint256:
    o: uint256 = 1
    for i: uint256 in range(256):
        o = uint256_mulmod(o, o, modulus)
        if exponent & shift(1, 255 - i) != 0:
            o = uint256_mulmod(o, base, modulus)
    return o
    """

    c = get_contract_with_gas_estimation(modexper)
    assert c.exponential(3, 5, 100) == 43
    assert c.exponential(2, 997, 997) == 2


def test_uint256_mulmod_ext_call(
    w3, side_effects_contract, assert_side_effects_invoked, get_contract
):
    code = """
interface Foo:
    def foo(x: uint256) -> uint256: nonpayable

@external
def foo(f: Foo) -> uint256:
    return uint256_mulmod(200, 3, extcall f.foo(601))
    """

    c1 = side_effects_contract("uint256")
    c2 = get_contract(code)

    assert c2.foo(c1.address) == 600

    assert_side_effects_invoked(c1, lambda: c2.foo(c1.address, transact={}))


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


def test_uint256_mulmod_evaluation_order(get_contract_with_gas_estimation):
    code = """
a: uint256

@external
def foo1() -> uint256:
    self.a = 1
    return uint256_mulmod(self.a, 2, self.bar())

@external
def foo2() -> uint256:
    self.a = 1
    return uint256_mulmod(self.bar(), self.a, 2)

@external
def foo3() -> uint256:
    self.a = 1
    return uint256_mulmod(2, self.a, self.bar())

@internal
def bar() -> uint256:
    self.a = 7
    return 5
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo1() == 2
    assert c.foo2() == 1
    assert c.foo3() == 2

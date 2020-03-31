def test_state_accessor(get_contract_with_gas_estimation_for_constants):
    state_accessor = """
y: map(int128, int128)

@public
def oo():
    self.y[3] = 5

@public
def foo() -> int128:
    return self.y[3]

    """

    c = get_contract_with_gas_estimation_for_constants(state_accessor)
    c.oo(transact={})
    assert c.foo() == 5


def test_getter_code(get_contract_with_gas_estimation_for_constants):
    getter_code = """
struct W:
    a: uint256
    b: int128[7]
    c: bytes[100]
    d: map(address, int128)
    e: int128[3][3]
    f: uint256
    g: uint256
x: public(uint256)
y: public(int128[5])
z: public(bytes[100])
w: public(map(int128, W))

@public
def __init__():
    self.x = as_wei_value(7, "wei")
    self.y[1] = 9
    self.z = b"cow"
    self.w[1].a = 11
    self.w[1].b[2] = 13
    self.w[1].c = b"horse"
    self.w[1].d[0x1234567890123456789012345678901234567890] = 15
    self.w[2].e[1][2] = 17
    self.w[3].f = 750
    self.w[3].g = 751
    """

    c = get_contract_with_gas_estimation_for_constants(getter_code)
    assert c.x() == 7
    assert c.y(1) == 9
    assert c.z() == b"cow"
    assert c.w__a(1) == 11
    assert c.w__b(1, 2) == 13
    assert c.w__c(1) == b"horse"
    assert c.w__d(1, "0x1234567890123456789012345678901234567890") == 15
    assert c.w__e(2, 1, 2) == 17
    assert c.w__f(3) == 750
    assert c.w__g(3) == 751

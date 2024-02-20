def test_state_accessor(get_contract_with_gas_estimation_for_constants):
    state_accessor = """
y: HashMap[int128, int128]

@external
def oo():
    self.y[3] = 5

@external
def foo() -> int128:
    return self.y[3]

    """

    c = get_contract_with_gas_estimation_for_constants(state_accessor)
    c.oo(transact={})
    assert c.foo() == 5


def test_getter_code(get_contract_with_gas_estimation_for_constants):
    getter_code = """
interface V:
    def foo(): nonpayable

struct W:
    a: uint256
    b: int128[7]
    c: Bytes[100]
    e: int128[3][3]
    f: uint256
    g: uint256
x: public(uint256)
y: public(int128[5])
z: public(Bytes[100])
w: public(HashMap[int128, W])
a: public(uint256[10][10])
b: public(HashMap[uint256, HashMap[address, uint256[4]]])
c: public(constant(uint256)) = 1
d: public(immutable(uint256))
e: public(immutable(uint256[2]))
f: public(constant(uint256[2])) = [3, 7]
g: public(constant(V)) = V(0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF)

@deploy
def __init__():
    self.x = as_wei_value(7, "wei")
    self.y[1] = 9
    self.z = b"cow"
    self.w[1].a = 11
    self.w[1].b[2] = 13
    self.w[1].c = b"horse"
    self.w[2].e[1][2] = 17
    self.w[3].f = 750
    self.w[3].g = 751
    self.a[1][4] = 666
    self.b[42][self] = [5,6,7,8]
    d = 1729
    e = [2, 3]
    """

    c = get_contract_with_gas_estimation_for_constants(getter_code)
    assert c.x() == 7
    assert c.y(1) == 9
    assert c.z() == b"cow"
    assert c.w(1)[0] == 11  # W.a
    assert c.w(1)[1][2] == 13  # W.b[2]
    assert c.w(1)[2] == b"horse"  # W.c
    assert c.w(2)[3][1][2] == 17  # W.e[1][2]
    assert c.w(3)[4] == 750  # W.f
    assert c.w(3)[5] == 751  # W.g
    assert c.a(1, 4) == 666
    assert c.b(42, c.address, 2) == 7
    assert c.c() == 1
    assert c.d() == 1729
    assert c.e(0) == 2
    assert [c.f(i) for i in range(2)] == [3, 7]
    assert c.g() == "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF"


def test_getter_mutability(get_contract):
    code = """
foo: public(uint256)
goo: public(String[69])
bar: public(uint256[4][5])
baz: public(HashMap[address, Bytes[100]])
potatoes: public(HashMap[uint256, HashMap[bytes32, uint256[4]]])
nyoro: public(constant(uint256)) = 2
kune: public(immutable(uint256))

@deploy
def __init__():
    kune = 2
"""

    contract = get_contract(code)

    for item in contract._classic_contract.abi:
        if item["type"] == "constructor":
            continue
        assert item["stateMutability"] == "view"

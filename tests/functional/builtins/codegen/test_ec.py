G1 = [1, 2]

G1_times_two = [
    1368015179489954701390400359078579693043519447331113978918064868415326638035,
    9918110051302171585080402603319702774565515993150576347155970296011118125764,
]

G1_times_three = [
    3353031288059533942658390886683067124040920775575537747144343083137631628272,
    19321533766552368860946552437480515441416830039777911637913418824951667761761,
]

negative_G1 = [1, 21888242871839275222246405745257275088696311157297823662689037894645226208581]

curve_order = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def test_ecadd(get_contract_with_gas_estimation):
    ecadder = """
x3: uint256[2]
y3: uint256[2]

@external
def _ecadd(x: uint256[2], y: uint256[2]) -> uint256[2]:
    return ecadd(x, y)

@external
def _ecadd2(x: uint256[2], y: uint256[2]) -> uint256[2]:
    x2: uint256[2] = x
    y2: uint256[2] = [y[0], y[1]]
    return ecadd(x2, y2)

@external
def _ecadd3(x: uint256[2], y: uint256[2]) -> uint256[2]:
    self.x3 = x
    self.y3 = [y[0], y[1]]
    return ecadd(self.x3, self.y3)

    """
    c = get_contract_with_gas_estimation(ecadder)

    assert c._ecadd(G1, G1) == G1_times_two
    assert c._ecadd2(G1, G1_times_two) == G1_times_three
    assert c._ecadd3(G1, [0, 0]) == G1
    assert c._ecadd3(G1, negative_G1) == [0, 0]


def test_ecadd_internal_call(get_contract_with_gas_estimation):
    code = """
@internal
def a() -> uint256[2]:
    return [1, 2]

@external
def foo() -> uint256[2]:
    return ecadd([1, 2], self.a())
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == G1_times_two


def test_ecadd_ext_call(w3, side_effects_contract, assert_side_effects_invoked, get_contract):
    code = """
interface Foo:
    def foo(x: uint256[2]) -> uint256[2]: payable

@external
def foo(a: Foo) -> uint256[2]:
    return ecadd([1, 2], extcall a.foo([1, 2]))
    """
    c1 = side_effects_contract("uint256[2]")
    c2 = get_contract(code)

    assert c2.foo(c1.address) == G1_times_two

    assert_side_effects_invoked(c1, lambda: c2.foo(c1.address, transact={}))


def test_ecadd_evaluation_order(get_contract_with_gas_estimation):
    code = """
x: uint256[2]

@internal
def bar() -> uint256[2]:
    self.x = ecadd([1, 2], [1, 2])
    return [1, 2]

@external
def foo() -> bool:
    self.x = [1, 2]
    a: uint256[2] = ecadd([1, 2], [1, 2])
    b: uint256[2] = ecadd(self.x, self.bar())
    return a[0] == b[0] and a[1] == b[1]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True


def test_ecmul(get_contract_with_gas_estimation):
    ecmuller = """
x3: uint256[2]
y3: uint256

@external
def _ecmul(x: uint256[2], y: uint256) -> uint256[2]:
    return ecmul(x, y)

@external
def _ecmul2(x: uint256[2], y: uint256) -> uint256[2]:
    x2: uint256[2] = x
    y2: uint256 = y
    return ecmul(x2, y2)

@external
def _ecmul3(x: uint256[2], y: uint256) -> uint256[2]:
    self.x3 = x
    self.y3 = y
    return ecmul(self.x3, self.y3)

"""
    c = get_contract_with_gas_estimation(ecmuller)

    assert c._ecmul(G1, 0) == [0, 0]
    assert c._ecmul(G1, 1) == G1
    assert c._ecmul(G1, 3) == G1_times_three
    assert c._ecmul(G1, curve_order - 1) == negative_G1
    assert c._ecmul(G1, curve_order) == [0, 0]


def test_ecmul_internal_call(get_contract_with_gas_estimation):
    code = """
@internal
def a() -> uint256:
    return 3

@external
def foo() -> uint256[2]:
    return ecmul([1, 2], self.a())
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == G1_times_three


def test_ecmul_ext_call(w3, side_effects_contract, assert_side_effects_invoked, get_contract):
    code = """
interface Foo:
    def foo(x: uint256) -> uint256: payable

@external
def foo(a: Foo) -> uint256[2]:
    return ecmul([1, 2], extcall a.foo(3))
    """
    c1 = side_effects_contract("uint256")
    c2 = get_contract(code)

    assert c2.foo(c1.address) == G1_times_three

    assert_side_effects_invoked(c1, lambda: c2.foo(c1.address, transact={}))


def test_ecmul_evaluation_order(get_contract_with_gas_estimation):
    code = """
x: uint256[2]

@internal
def bar() -> uint256:
    self.x = ecmul([1, 2], 3)
    return 3

@external
def foo() -> bool:
    self.x = [1, 2]
    a: uint256[2] = ecmul([1, 2], 3)
    b: uint256[2] = ecmul(self.x, self.bar())
    return a[0] == b[0] and a[1] == b[1]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True

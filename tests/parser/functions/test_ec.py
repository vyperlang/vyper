G1 = [1, 2]

G1_times_two = [
    1368015179489954701390400359078579693043519447331113978918064868415326638035,
    9918110051302171585080402603319702774565515993150576347155970296011118125764
]

G1_times_three = [
    3353031288059533942658390886683067124040920775575537747144343083137631628272,
    19321533766552368860946552437480515441416830039777911637913418824951667761761
]

negative_G1 = [
    1,
    21888242871839275222246405745257275088696311157297823662689037894645226208581
]

curve_order = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def test_ecadd(get_contract_with_gas_estimation):
    ecadder = """
x3: num256[2]
y3: num256[2]

@public
def _ecadd(x: num256[2], y: num256[2]) -> num256[2]:
    return ecadd(x, y)

@public
def _ecadd2(x: num256[2], y: num256[2]) -> num256[2]:
    x2: num256[2] = x
    y2: num256[2] = [y[0], y[1]]
    return ecadd(x2, y2)

@public
def _ecadd3(x: num256[2], y: num256[2]) -> num256[2]:
    self.x3 = x
    self.y3 = [y[0], y[1]]
    return ecadd(self.x3, self.y3)

    """
    c = get_contract_with_gas_estimation(ecadder)

    assert c._ecadd(G1, G1) == G1_times_two
    assert c._ecadd2(G1, G1_times_two) == G1_times_three
    assert c._ecadd3(G1, [0, 0]) == G1
    assert c._ecadd3(G1, negative_G1) == [0, 0]


def test_ecmul(get_contract_with_gas_estimation):
    ecmuller = """
x3: num256[2]
y3: num256

@public
def _ecmul(x: num256[2], y: num256) -> num256[2]:
    return ecmul(x, y)

@public
def _ecmul2(x: num256[2], y: num256) -> num256[2]:
    x2: num256[2] = x
    y2: num256 = y
    return ecmul(x2, y2)

@public
def _ecmul3(x: num256[2], y: num256) -> num256[2]:
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

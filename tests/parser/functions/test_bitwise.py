def test_test_bitwise(get_contract_with_gas_estimation):
    test_bitwise = """
@public
def _bitwise_and(x: num256, y: num256) -> num256:
    return bitwise_and(x, y)

@public
def _bitwise_or(x: num256, y: num256) -> num256:
    return bitwise_or(x, y)

@public
def _bitwise_xor(x: num256, y: num256) -> num256:
    return bitwise_xor(x, y)

@public
def _bitwise_not(x: num256) -> num256:
    return bitwise_not(x)

@public
def _shift(x: num256, y: num) -> num256:
    return shift(x, y)
    """

    c = get_contract_with_gas_estimation(test_bitwise)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    assert c._bitwise_and(x, y) == (x & y)
    assert c._bitwise_or(x, y) == (x | y)
    assert c._bitwise_xor(x, y) == (x ^ y)
    assert c._bitwise_not(x) == 2**256 - 1 - x
    assert c._shift(x, 3) == x * 8
    assert c._shift(x, 255) == 0
    assert c._shift(y, 255) == 2**255
    assert c._shift(x, 256) == 0
    assert c._shift(x, 0) == x
    assert c._shift(x, -1) == x // 2
    assert c._shift(x, -3) == x // 8
    assert c._shift(x, -256) == 0

    print("Passed bitwise operation tests")

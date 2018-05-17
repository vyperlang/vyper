from decimal import Decimal


def test_minmax(get_contract_with_gas_estimation):
    minmax_test = """
@public
def foo() -> decimal:
    return min(3, 5) + max(10, 20) + min(200.1, 400) + max(3000, 8000.02) + min(50000.003, 70000.004)

@public
def goo() -> uint256:
    return min(convert(3, 'uint256'), convert(5, 'uint256')) + max(convert(40, 'uint256'), convert(80, 'uint256'))
    """

    c = get_contract_with_gas_estimation(minmax_test)
    assert c.foo() == Decimal('58223.123')
    assert c.goo() == 83

    print("Passed min/max test")

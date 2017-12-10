def test_minmax(get_contract_with_gas_estimation):
    minmax_test = """
@public
def foo() -> decimal:
    return min(3, 5) + max(10, 20) + min(200.1, 400) + max(3000, 8000.02) + min(50000.003, 70000.004)

@public
def goo() -> num256:
    return num256_add(min(as_num256(3), as_num256(5)), max(as_num256(40), as_num256(80)))
    """

    c = get_contract_with_gas_estimation(minmax_test)
    assert c.foo() == 58223.123
    assert c.goo() == 83

    print("Passed min/max test")

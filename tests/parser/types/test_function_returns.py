def test_function_return_list_in_tuple(get_contract_with_gas_estimation):
    list_tester_code = """
@public
def foo() -> (uint256, uint256[2]):
    return (0, [0, 1])
    """

    c = get_contract_with_gas_estimation(list_tester_code)
    assert isinstance(c.foo()[1], list)
    assert len(c.foo()[1]) == 2
    assert c.foo()[0] == 0
    assert c.foo()[1].sort() == [0, 1].sort()
    print("Passed functions return as tuple")

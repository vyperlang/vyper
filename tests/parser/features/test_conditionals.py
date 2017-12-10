def test_conditional_return_code(get_contract_with_gas_estimation):
    conditional_return_code = """
@public
def foo(i: bool) -> num:
    if i:
        return 5
    else:
        assert 2
        return 7
    return 11
    """

    c = get_contract_with_gas_estimation(conditional_return_code)
    assert c.foo(True) == 5
    assert c.foo(False) == 7

    print('Passed conditional return tests')

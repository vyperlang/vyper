def test_constant_test(get_contract_with_gas_estimation_for_constants):
    constant_test = """
@public
@constant
def foo() -> int128:
    return 5
    """

    c = get_contract_with_gas_estimation_for_constants(constant_test)
    assert c.foo() == 5

    print("Passed constant function test")

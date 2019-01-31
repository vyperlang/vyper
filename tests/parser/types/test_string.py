
def test_string_return(get_contract_with_gas_estimation):
    code = """
@public
def testb() -> string[100]:
    a: string[100] = "test return"
    return a
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb() == "test return"

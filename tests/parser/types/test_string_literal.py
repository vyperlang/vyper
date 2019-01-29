
def test_string_literal_return(get_contract_with_gas_estimation):
    code = """
@public
def test() -> string[100]:
    return "hello world!"


@public
def testb() -> bytes[100]:
    return b"hello world!"
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == "hello world!"
    assert c.testb() == b"hello world!"

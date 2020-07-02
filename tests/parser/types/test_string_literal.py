def test_string_literal_return(get_contract_with_gas_estimation):
    code = """
@external
def test() -> String[100]:
    return "hello world!"


@external
def testb() -> Bytes[100]:
    return b"hello world!"
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == "hello world!"
    assert c.testb() == b"hello world!"


def test_string_convert(get_contract_with_gas_estimation):
    code = """
@external
def testb() -> String[100]:
    return convert(b"hello world!", String[100])

@external
def testbb() -> String[100]:
    return convert(convert("hello world!", Bytes[100]), String[100])
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb() == "hello world!"
    assert c.testbb() == "hello world!"


def test_str_assign(get_contract_with_gas_estimation):
    code = """
@external
def test() -> String[100]:
    a: String[100] = "baba black sheep"
    return a
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == "baba black sheep"

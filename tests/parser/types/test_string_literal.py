
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


def test_string_convert(get_contract_with_gas_estimation):
    code = """
@public
def testb() -> string[100]:
    return convert(b"hello world!", string[100])

@public
def testbb() -> string[100]:
    return convert(convert("hello world!", bytes[100]), string[100])
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb() == "hello world!"
    assert c.testbb() == "hello world!"


def test_str_assign(get_contract_with_gas_estimation):
    code = """
@public
def test() -> string[100]:
    a: string[100] = "baba black sheep"
    return a
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == "baba black sheep"

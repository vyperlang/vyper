
def test_string_return(get_contract_with_gas_estimation):
    code = """
@public
def testb() -> string[100]:
    a: string[100] = "test return"
    return a

@public
def testa(inp: string[100]) -> string[100]:
    return inp
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testa('meh') == "meh"
    assert c.testb() == "test return"


def test_string_concat(get_contract_with_gas_estimation):
    code = """
@public
def testb(inp: string[10]) -> string[128]:
    a: string[100] = "return message:"
    a = concat(a, " ", inp)
    return a

@public
def testa(inp: string[10]) -> string[160]:
    a: string[100] = "<-- return message"
    return concat("Funny ", inp, " ", inp, a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb('bob') == "return message: bob"
    assert c.testa('foo') == "Funny foo foo<-- return message"

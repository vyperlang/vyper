
def test_convert_from_bool(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> bool:
    val: bool = True and True and False
    return val

@public
def bar() -> bool:
    val: bool = True or True or False
    return val

@public
def foobar() -> bool:
    val: bool = False and True or False
    return val
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == False
    assert c.bar() == True
    assert c.foobar() == False

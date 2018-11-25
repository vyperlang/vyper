
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

@public
def oof() -> bool:
    val: bool = False or False or False or False or False or True
    return val

@public
def rab() -> bool:
    val: bool = True and True and True and True and True and False
    return val

@public
def oofrab() -> bool:
    val: bool = False and True or False and True or False and False or True
    return val
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() is False
    assert c.bar() is True
    assert c.foobar() is False
    assert c.oof() is True
    assert c.rab() is False
    assert c.oofrab() is True

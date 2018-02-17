from vyper.exceptions import StructureException
from pytest import raises


def test_semicolon_prohibited(get_contract):
    code = """@public
def test() -> num:
    a: num = 1; b: num = 2
    return a + b
    """

    with raises(StructureException):
        get_contract(code)


def test_valid_semicolons(get_contract):
    code = """
@public
def test() -> num:
    a: num = 1
    b: num = 2
    s: bytes <= 300 = "this should not be a problem; because it is in a string"
    s = \"\"\"this should not be a problem; because it's in a string\"\"\"
    s = 'this should not be a problem;;; because it\\\'s in a string'
    s = '''this should not ; \'cause it\'s in a string'''
    s = "this should not be \\\"; because it's in a ;\\\"string;\\\";"
    return a + b
    """
    c = get_contract(code)
    assert c.test() == 3


def test_external_contract_definition_alias(get_contract):
    contract_1 = """
@public
def bar() -> num:
    return 1
    """

    contract_2 = """
contract Bar():
    def bar() -> num: pass

bar_contract: Bar

@public
def foo(contract_address: contract(Bar)) -> num:
    self.bar_contract = contract_address
    return self.bar_contract.bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c2.foo(c1.address) == 1

from pytest import raises
from vyper.exceptions import VariableDeclarationException


def test_permanent_variables_test(get_contract_with_gas_estimation):
    permanent_variables_test = """
var: {a: int128, b: int128}

@public
def __init__(a: int128, b: int128):
    self.var.a = a
    self.var.b = b

@public
def returnMoose() -> int128:
    return self.var.a * 10 + self.var.b
    """

    c = get_contract_with_gas_estimation(permanent_variables_test, *[5, 7])
    assert c.returnMoose() == 57
    print('Passed init argument and variable member test')


def test_missing_global(get_contract):
    code = """
@public
def a() -> int128:
    return self.b
    """

    with raises(VariableDeclarationException):
        get_contract(code)

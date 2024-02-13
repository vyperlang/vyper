from pytest import raises

from vyper.exceptions import UndeclaredDefinition


def test_permanent_variables_test(get_contract_with_gas_estimation):
    permanent_variables_test = """
struct Var:
    a: int128
    b: int128
var: Var

@deploy
def __init__(a: int128, b: int128):
    self.var.a = a
    self.var.b = b

@external
def returnMoose() -> int128:
    return self.var.a * 10 + self.var.b
    """

    c = get_contract_with_gas_estimation(permanent_variables_test, *[5, 7])
    assert c.returnMoose() == 57
    print("Passed init argument and variable member test")


def test_missing_global(get_contract):
    code = """
@external
def a() -> int128:
    return self.b
    """

    with raises(UndeclaredDefinition):
        get_contract(code)

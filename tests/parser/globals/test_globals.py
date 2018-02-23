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

    c = get_contract_with_gas_estimation(permanent_variables_test, args=[5, 7])
    assert c.returnMoose() == 57
    print('Passed init argument and variable member test')

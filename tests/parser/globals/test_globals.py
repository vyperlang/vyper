def test_permanent_variables_test(get_contract_with_gas_estimation):
    permanent_variables_test = """
var: {a: num, b: num}

@public
def __init__(a: num, b: num):
    self.var.a = a
    self.var.b = b

@public
def returnMoose() -> num:
    return self.var.a * 10 + self.var.b
    """

    c = get_contract_with_gas_estimation(permanent_variables_test, args=[5, 7])
    assert c.returnMoose() == 57
    print('Passed init argument and variable member test')

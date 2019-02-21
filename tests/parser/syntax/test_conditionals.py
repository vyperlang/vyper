def test_conditional_return_code(get_contract_with_gas_estimation):
    conditional_return_code = """
@private
def mkint() -> int128:
    return 1

@public
def test_zerovalent():
    if True:
        self.mkint()

@public
def test_valency_mismatch():
    if True:
        self.mkint()
    else:
        pass
    """

    c = get_contract_with_gas_estimation(conditional_return_code)

    print('Passed conditional return tests')

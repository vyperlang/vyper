def test_private_test(get_contract_with_gas_estimation):
    private_test_code = """
@private
def a() -> int128:
    return 5

@public
def returnten() -> int128:
    return self.a() * 2
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.returnten() == 10


def test_private_with_more_vars(get_contract_with_gas_estimation):
    private_test_code = """
@private
def afunc() -> int128:
    a: int128 = 1
    return 444

@public
def return_it() -> int128:
    a: int128 = 222
    b: int128 = 111
    c: int128 = self.afunc()
    return a + b + c
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.return_it() == 777

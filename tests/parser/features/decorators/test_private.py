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


def test_private_with_more_vars(get_contract):
    private_test_code = """
@private
def afunc() -> int128:
    a: int128 = 4
    b: int128 = 40
    c: int128 = 400
    return a + b + c


@public
def return_it() -> int128:
    a: int128 = 111
    b: int128 = 222
    c: int128 = self.afunc()
    return a + b + c
    """

    c = get_contract(private_test_code)
    assert c.return_it() == 777


def test_private_with_more_vars_nested(get_contract_with_gas_estimation):
    private_test_code = """
@private
def more() -> int128:
    a: int128 = 11
    b: int128 = 100
    c: int128 = 1
    return a + b + c

@private
def afunc() -> int128:
    a: int128 = 1
    a += self.more()
    return 444 + self.more()

@public
def return_it() -> int128:
    a: int128 = 222
    b: int128 = 111
    c: int128 = self.more()
    return a + b + c
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.return_it() == 444

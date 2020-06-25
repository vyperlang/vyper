def test_null_code(get_contract_with_gas_estimation):
    null_code = """
@public
def foo():
    pass
    """
    c = get_contract_with_gas_estimation(null_code)
    c.foo()


def test_basic_code(get_contract_with_gas_estimation):
    basic_code = """
@public
def foo(x: int128) -> int128:
    return x * 2

    """
    c = get_contract_with_gas_estimation(basic_code)
    assert c.foo(9) == 18

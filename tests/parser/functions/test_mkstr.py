def test_mkstr(get_contract_with_gas_estimation):
    code = """
@external
def foo(inp: uint256) -> String[78]:
    return str(inp)
    """

    c = get_contract_with_gas_estimation(code)
    for i in [1, 2, 2 ** 256 - 1, 0]:
        assert c.foo(i) == str(i), (i, c.foo(i))

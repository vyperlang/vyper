def test_test_length(get_contract_with_gas_estimation):
    test_length = """
y: Bytes[10]

@external
def foo(inp: uint256) -> String[78]:
    return uint2str(inp)
    """

    c = get_contract_with_gas_estimation(test_length)
    for i in [1, 2, 2 ** 256 - 1, 0]:
        assert c.foo(i) == str(i), (i, c.foo(i))

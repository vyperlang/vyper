def test_method_id_test(get_contract_with_gas_estimation):
    method_id_test = """
@public
def double(x: num) -> num:
    return x * 2

@public
def returnten() -> num:
    ans: bytes <= 32 = raw_call(self, concat(method_id("double(int128)"), convert(5, 'bytes32')), gas=50000, outsize=32)
    return convert(convert(ans, 'bytes32'), 'num')
    """
    c = get_contract_with_gas_estimation(method_id_test)
    assert c.returnten() == 10
    print("Passed method ID test")
